import os
from datetime import datetime

from Products.Five.browser import BrowserView
from Products.CMFCore.utils import getToolByName

from collective.sendaspdf import transforms
from collective.sendaspdf.utils import find_filename, update_relative_url

from collective.sendaspdf.utils import md5_hash
from collective.sendaspdf.utils import extract_from_url

class BaseView(BrowserView):
    """ Class used to factorize some code for the different views
    used in the product.
    """
    error_mapping = {}

    def __init__(self, *args, **kwargs):
        """ We just need to define some instance variables.
        """
        super(BaseView, self).__init__(*args, **kwargs)

        # The list of errors found when checking the form.
        self.errors = []
        
        # We get the configuration from the portal_sendaspdf
        self.pdf_tool = getToolByName(self.context,
                                      'portal_sendaspdf')
        self.tempdir = self.pdf_tool.tempdir
        self.salt = self.pdf_tool.salt
        self.pdf_generator = self.pdf_tool.pdf_generator
        self.filename_in_mail = self.pdf_tool.filename_in_mail

        self.pdf_file = None
        self.filename = ''

    def get_lang(self):
        """ Finds the language to use.
        """
        props = getToolByName(self.context,
                              'portal_properties')
        return props.site_properties.getProperty('default_language') or 'en'

    def get_user(self):
        """ Returns the currently logged-in user.
        """
        mtool = getToolByName(self.context, 'portal_membership')
        if mtool.isAnonymousUser():
            return

        return mtool.getAuthenticatedMember()

    def get_user_fullname(self):
        """ Returns the currently logged-in user's fullname.
        """
        member = self.get_user()
        if member:
            return member.getProperty('fullname')

    def get_user_email(self):
        """ Returns the currently logged-in user's email.
        """
        member = self.get_user()
        if member:
            return member.getProperty('email')

    def generate_filename_prefix(self):
        """ Returns the user's email hashed in md5 followed
        by an underscore.
        If we can not get an email (the user is anonymous or
        email is not mandatory in the system), returns an empty
        string.

        We extract it from 'generate_temp_filename as we will
        also use this sytem to be sure that the user has
        access to the file when sending it.
        """
        email = self.get_user_email()
        if not email:
            return ''

        return '%s_' % md5_hash(email, self.salt)

    def get_page_source(self):
        """ Returns the HTML source of a web page, considering
        that the URL of the page is contained in the form under
        the 'page_url' key.
        """

        if not 'page_url' in self.request.form:
            self.errors.append('no_source')
            return

        url = self.request.form['page_url']
        context_url = self.context.absolute_url()

        view_name, get_params = extract_from_url(url, context_url)

        # Now we will reinject the GET parameters in the request.
        if get_params:
            for key in get_params:
                self.request.form[key] = get_params[key]

        if not view_name:
            ttool = getToolByName(self.context, 'portal_types')
            if self.context.portal_type in ttool:
                context_type = ttool[self.context.portal_type]
                view_name = context_type.getProperty('immediate_view')

        try:
            view = self.context.restrictedTraverse(view_name)
        except:
            return

        return update_relative_url(view(), self.context)


    def generate_temp_filename(self):
        """ Generates the filename used to store the PDF file.
        Basically the md5 hash of th user's email followed
        by a timestamp.
        If the user is anonymous, just use the timestamp.
        In case of conflict, we just happen '-x' at the end.
        """
        prefix = self.generate_filename_prefix()
        now = datetime.now()
        # Ok that might not be the best timestamp system, but it's
        # enough for our needs.
        timestamp = ''.join([str(x) for x in now.timetuple()])
        filename = prefix + timestamp
        return find_filename(self.tempdir,
                             filename)

    def get_extra_options(self):
        options = []
        tool_options = self.pdf_tool.make_options()

        # Simple options without value.
        for opt in ['toc', 'book']:
            # Default option in the tool
            t_val = tool_options.get(opt, False)
            # User can specify in the download link '--no-book' for example.
            r_noval = self.request.get('--no-%s' % opt, None)
            # User can specify in the downloak link '--book'.
            r_val = self.request.get(opt, None)
            
            if (t_val and r_noval is None) or (r_val is not None):
                options.append('--%s' % opt)

        # Options expecting a value.
        for opt in ['margin-top','margin-bottom', 'margin-left', 'margin-right',
                    'toc-header-text', 'cover']:
            # The value specified in the link will override the one specified in
            # the tool.

            value = self.request.get(opt, None) or tool_options.get(opt, None)
            if value is not None:
                options.append(str(value))
                options.append('--%s' % opt)

        return options

    def generate_pdf_file(self, source):
        """ Generates a PDF file from the given source
        (string containing the HTML source of a page).
        """
        filename = self.generate_temp_filename()
        if not filename:
            self.errors.append('filename_generation_failed')
            return

        try:
            transform_module = getattr(transforms, self.pdf_generator)
        except AttributeError:
            self.errors.append('wrong_generator_configuration')
            return

        self.filename = filename
        url = self.context.absolute_url()

        if self.pdf_tool.always_print_css:
            print_css = True
        else:
            print_css = self.context.portal_type in \
                        self.pdf_tool.print_css_types

        export_file, err = transform_module.html_to_pdf(source,
                                                        self.tempdir,
                                                        filename,
                                                        url,
                                                        print_css,
                                                        self.get_extra_options())
        if err:
            self.errors.append('pdf_creation_failed')
            return

        self.pdf_tool.registerPDF(filename)
        self.pdf_file = export_file
        self.pdf_file.close()

    def make_pdf(self):
        """ Fetches the page source and generates a PDF.
        """
        source = self.get_page_source()
        if not self.errors:
            self.generate_pdf_file(source)

    def show_error_message(self, error_name):
        """ Tells if an error message should be shown in the template.
        """
        return error_name in self.errors

    def class_for_field(self, fieldname):
        """ Returns the class that should be applied to a field
        in the forms displayed by the product.
        """
        base_class = 'field'
        error_class = ' error'
        if not fieldname in self.error_mapping:
            if fieldname in self.errors:
                base_class += error_class
            return base_class

        for error_name in self.error_mapping[fieldname]:
            if self.show_error_message(error_name):
                return base_class + error_class
        return base_class

    def check_pdf_accessibility(self):
        """ Check that the filename given in the request
        can be accessed by the user.
        """
        if not 'pdf_name' in self.request.form:
            # Should not happen.
            self.errors.append('file_not_specified')
            return

        filename = self.request.form['pdf_name']
        prefix = self.generate_filename_prefix()
        if not filename.startswith(prefix):
            # The user should not be able to see this file.
            self.errors.append('file_unauthorized')
            return

        if not filename in os.listdir(self.tempdir):
            self.errors.append('file_not_found')
            self.request.response.setStatus(404)
            return
