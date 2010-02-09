import sys, os, hashlib
from optparse import make_option
from commands import getstatusoutput

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.management.color  import no_style

from sass.models import SassModel

class SassConfigException(Exception):
    pass

class Command(BaseCommand):
    """
        The user may whish to keep their sass files in their MEDIA_ROOT directory,
        or they may wish them to be somewhere outsite - even outside their project
        directory. We try to support both.
        
        The same is true for the CSS output file. We recommend putting it in the 
        MEDIA_ROOT but if there is a reason not to, we support that as well.
    """
    
    requires_model_validation = False
    can_import_settings = True
    style = no_style()
    
    option_list = BaseCommand.option_list + ( 
        make_option('--style', '-t', dest='sass_style', default='nested', help='Sass output style. Can be nested (default), compact, compressed, or expanded.'),
        make_option('--list', '-l', action='store_true', dest='list_sass' , default=None, help='Display information about the status of your sass files.'),
        make_option('--force', '-f', action='store_true', dest='force_sass', default=False, help='Force sass to run.'),
    )
    help = 'Converts Sass files into CSS.'
    
    
    def handle(self, *args, **kwargs):
        try:
            self.bin = settings.SASS_BIN
            # test that binary defined exists
            if not os.path.exists(self.bin):
                sys.stderr.write(self.style.ERROR('Sass binary defined by SASS_BIN does not exist: %s\n' %bin))
                return
        except:
            sys.stderr.write(self.style.ERROR('SASS_BIN is not defined in settings.py file.\n'))
            return
        
        # make sure the Sass style given is valid.
        self.sass_style = kwargs.get('sass_style')
        if self.sass_style not in ('nested', 'compact', 'compressed', 'expanded'):
            sys.stderr.write(self.style.ERROR("Invalid sass style argument: %s\n") %self.sass_style)
            return
        
        if kwargs.get('list_sass'):
            self.process_sass_list()
        else:
            self.process_sass_dir(force=kwargs.get('force_sass'))
            
    
    def process_sass_list(self):
        """
        We check to see if the Sass outlined in the SASS setting are different from what the databse
        has stored. We only care about listing those files that are in the SASS setting. Ignore the 
        settings in the DB if the files have been removed.
        
        Output in the format only if there are differences.:
        
            <name> <old_hash> <current_hash>
            
            If there are no changes, output at the end of the script that there were no changes.
        
        """
        
        # process the Sass information in the settings.
        sass_struct = self.build_sass_structure()
        for sass in sass_struct:
            # get the digest we have stored and compare to the hash we have on disk.
            try:
                # hash from db.
                sass_obj = SassModel.objects.get(name=sass['name'])
                sass_digest = sass_obj.digest
            except (SassModel.DoesNotExist):
                sass_digest = None
                
            try:
                # digest from disk.
                sass_file_digest = self.md5_file(sass['input'])
            except SassConfigException, e:
                # not really sure what we want to do with this exception.
                raise e
            
            same_digest = sass_file_digest == sass_digest
            
            print "%s: %s" %(sass['name'], "NO CHANGE" if same_digest else "UPDATE REQUIRED")
            if not same_digest:
                # give out information about the changes.
                print "-------------------------------------"
                print sass['input']
                print "Previous: %s" %sass_digest
                print "Current:  %s\n" %sass_file_digest
            
    def build_sass_structure(self):
        try:
            sass_definitions = settings.SASS
        except:
            sass_definitions = ()
            
        sass_struct = []
        for sass_def in sass_definitions:
            try:
                sass_name = sass_def.get('name', None)
                sass_details = sass_def.get('details', {})
                sass_input = sass_details.get('input', None)
                sass_output = sass_details.get('output', None)
                
                # i hate generic exception message - try to give the user a meaningful message about what exactly the problem is.
                for prop in [('name', sass_name), ('details', sass_details), ('input', sass_input), ('output', sass_output)]:
                    if not prop[1]:
                        raise SassConfigException('Sass \'%s\' property not defined in configuration:\n%s\n' %(prop[0], sass_def))                
            except SassConfigException, e:
                sys.stderr.write(self.style.ERROR(e.message))
                return
            sass_input_root = self.get_file_path(sass_input)
            sass_output_root = self.get_file_path(sass_output)
            sass_struct.append({
                'name' : sass_name,
                'input' : sass_input_root,
                'output' : sass_output_root,
            })
        return sass_struct    
    
    
    def process_sass_dir(self, force=False):
        if force:
            print "Forcing sass to run on all files."
        
        sass_struct = self.build_sass_structure()
        for sass_info in sass_struct:
            try:
                self.process_sass_file(
                    sass_info.get('name'),
                    sass_info.get('input'),
                    sass_info.get('output'),
                    force
                )
            except SassConfigException, e:
                sys.stderr.write(self.style.ERROR(e.message))
            
            
    def process_sass_file(self, name, input_file, output_file, force):
        # check that the sass input file actually exists.
        if not os.path.exists(input_file):
            raise SassConfigException('The input path \'%s\' seems to be invalid.\n' %input_file)
        # make sure the output directory exists.
        output_path = output_file.rsplit('/', 1)[0]
        if not os.path.exists(output_path):
            # try to create path
            try:
                os.mkdirs(output_path, 0644)
            except os.error, e:
                raise SassConfigException(e.message)
            except AttributeError, e:
                # we have an older version of python that doesn't support os.mkdirs - fail gracefully.
                raise SassConfigException('Output path does not exist - please create manually: %s\n' %output_path)
        # everything should be in check - process files
        sass_dict = {
            'bin' : self.bin,
            'sass_style' : self.sass_style,
            'input' : input_file,
            'output' : output_file,
        }
        
        try:
            sass_obj = SassModel.objects.get(name=name)
        except SassModel.DoesNotExist, e:
            # create the new sass_obj
            sass_obj = SassModel()
        
        input_digest = self.md5_file(input_file)
        if not input_digest == sass_obj.digest or not os.path.exists(output_file) or force:
            print "Adding the sass: %s" %name
            cmd = "%(bin)s -t %(sass_style)s -C %(input)s > %(output)s" %sass_dict
            (status, output) = getstatusoutput(cmd)
            if not status == 0:
                raise SassConfException(output)
            # if we successfully generate the file, save the model to the DB.    
            sass_obj.name = name
            sass_obj.sass_path = input_file
            sass_obj.css_path = output_file
            sass_obj.digest = input_digest
            sass_obj.save()
        else:
            print "Skipping %s" %name
        
        
    def md5_file(self, filename):
        try:
            md5 = hashlib.md5()
            fd = open(filename,"rb")
            content = fd.readlines()
            fd.close()
            for line in content:
                md5.update(line)
            return md5.hexdigest()
        except IOError, e:
            raise SassConfigException(e.message)
    
        
    def get_file_path(self, path):
        if os.path.isabs(path):
            return path
        site_media = settings.MEDIA_ROOT
        return site_media + os.path.sep + path
        