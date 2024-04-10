import pywikibot
import pywikibot
import json

from exif import Image
import exiftool
import locale

from PIL import Image as PILImage

from datetime import datetime
from dateutil import parser
import os
import logging
import pprint
import subprocess
from transliterate import translit
from pywikibot.specialbots import UploadRobot
import tempfile
import warnings
import shutil
from tqdm import tqdm

import contextlib
import io

import placejpgconfig


class Fileprocessor:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    pp = pprint.PrettyPrinter(indent=4)

    langs_optional = placejpgconfig.langs_optional
    langs_primary = placejpgconfig.langs_primary
    
    exiftool_path = "exiftool"
    
    # TIFF LARGER THAN THIS VALUE WILL BE COMPRESSED TO WEBP 
    tiff2webp_min_size_mb = 55
    
    chunk_size = 10240000
    # chunk_size = 0
    
    photographer = placejpgconfig.photographer
    folder_keywords = ['commons_uploaded', 'commons_duplicates']
    wikidata_cache = dict()

    def convert_to_webp(self, filepath: str) -> str:
        """Convert image to webp.

        Args:
            source (pathlib.Path): Path to source image

        Returns:
            pathlib.Path: path to new image
        """
        destination = os.path.splitext(filepath)[0]+'.webp'

        image = PILImage.open(filepath)  # Open image
        image.save(destination, format="webp", lossless=False,
                   quality=98)  # Convert image to webp

        # copy metadata to webp require recent exiftool
        try:
            subprocess.check_output(["exiftool", "-ver"])
            cmd = ['exiftool', '-charset', 'utf8', '-tagsfromfile',
               filepath, '-overwrite_original',  destination]  # '-all:all' ,
            subprocess.run(cmd)
        except subprocess.CalledProcessError:
            print("Exiftool is not installed. WEBP file created without exif tags")

        return destination

    def input2filelist(self, filepath,mode=None):
        if os.path.isfile(filepath):
            files = [filepath]
            assert os.path.isfile(filepath)
            uploaded_folder_path = os.path.join(
                os.path.dirname(filepath), 'commons_uploaded')
        elif os.path.isdir(filepath):
            files = os.listdir(filepath)
            files = [os.path.join(filepath, x) for x in files]
            folder_keywords = self.folder_keywords
            if mode=='replace_duplicates':
                while 'commons_duplicates' in folder_keywords: folder_keywords.remove('commons_duplicates') 
            files = list(
                filter(lambda name: not any(keyword in name for keyword in folder_keywords), files))

            uploaded_folder_path = os.path.join(filepath, 'commons_uploaded')
        else:
            raise Exception("filepath should be file or directory")
        return files, uploaded_folder_path

    def prepare_wikidata_url(self, wikidata) -> str:
        # convert string https://www.wikidata.org/wiki/Q4412648 to Q4412648

        wikidata = str(wikidata).strip()
        wikidata = wikidata.replace('https://www.wikidata.org/wiki/', '')

        return wikidata

    def upload_file(self, filepath, commons_name, description, verify_description=False,ignore_warning=False):
        # The site object for Wikimedia Commons
        site = pywikibot.Site("commons", "commons")

        # The upload robot object
        bot = UploadRobot(
            [filepath],  # A list of files to upload
            description=description,  # The description of the file
            # keep original names of urls and files, otherwise it will ask to enter a name for each file
            use_filename=commons_name,
            keep_filename=True,  # Keep the filename as is
            # Ask for verification of the description
            verify_description=verify_description,
            targetSite=site,  # The site object for Wikimedia Commons
            aborts=True,  # List of the warning types to abort upload on
            chunk_size=self.chunk_size,
            ignore_warning=ignore_warning
        )
        print()
        print('=======================================================')
        print(commons_name.center(60, '*'))
        # Try to run the upload robot
        try:
            # bot.run()
            # SAVE pywikibot screen output to move photos to subdirs by errors
            f = io.StringIO()
            with contextlib.redirect_stderr(f):
                bot.run()
            pywikibot_output = f.getvalue()
            # print('>>>'+pywikibot_output+'<<<')
            return pywikibot_output
        except Exception as e:
            # Handle API errors
            print(f"API error: {e.code}: {e.info}")
            return False
        return None

    def deprecated_get_wikidata_simplified(self, wikidata) -> dict:
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        # get all claims of this wikidata objects

        if wikidata in self.wikidata_cache:
            return self.wikidata_cache[wikidata]

        cmd = ["wb", "gt", "--json", "--no-minimize", wikidata]
        response = subprocess.run(cmd, capture_output=True)
        object_wd = json.loads(response.stdout.decode())
        object_record = {'names': {}}
        try:
            object_record['names'] = {
                "en": object_wd["labels"]["en"],
                "ru": object_wd["labels"]["ru"],
            }
        except:
            raise ValueError('object https://www.wikidata.org/wiki/' +
                             wikidata+' must has name ru and name en')

        for lang in self.langs_optional:
            if lang in object_wd["labels"]:
                object_record['names'][lang] = object_wd["labels"][lang]
        if "P373" in object_wd["claims"]:
            object_record['commons'] = object_wd["claims"]["P373"][0]["value"]
        elif 'commonswiki' in object_wd["sitelinks"]:
            object_record['commons'] = object_wd["sitelinks"]["commonswiki"]["title"].replace(
                'Category:', '')
        else:
            object_record['commons'] = None

        if "P31" in object_wd["claims"]:
            object_record['instance_of_list'] = object_wd["claims"]["P31"]
        self.wikidata_cache[wikidata] = object_record

        return object_record

    def is_wikidata_id(self, text) -> bool:
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        # check if string is valid wikidata id
        if text.startswith('Q') and text[1:].isnumeric():
            return True
        else:
            return False

    def search_wikidata_by_string(self, text, stop_on_error=True) -> str:
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        cmd = ['wb', 'search', '--json', text]

        response = subprocess.run(cmd, capture_output=True)
        object_wd = json.loads(response.stdout.decode())
        if stop_on_error:
            if not len(object_wd) > 0:
                raise ValueError('not found in wikidata: '+text)
        self.logger.debug('found: '+text+' '+object_wd[0]['concepturi'])
        return object_wd[0]['id']

    def get_wikidata_labels(self, wikidata) -> dict:
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        cmd = ['wb', 'gt', '--props', 'labels', '--json', wikidata]
        response = subprocess.run(cmd, capture_output=True)
        object_wd = json.loads(response.stdout.decode())
        return object_wd['labels']
    
    def get_place_from_input(self,filename:str,street:str,geo_dict:dict,override_key='placeQ',geodata_attribute='wikidata')->str:
            '''
            return wikidata id of photo place
            diffirent input variants accepted:

            * upload-vehicle.py --street Q12345678 EP2D-0030.jpg
                    return Q12345678
            * upload-vehicle.py --street rail.gpkg EP2D-0030.jpg
                    read coordinates from EXIF, search by coordinates in rail.gpkg
                    open 1st layer in vector file, get 'wikidata' field value
            * upload-vehicle.py --street rail.gpkg EP2D-0030_placeQ12345678.jpg 
                    return Q12345678
            
            '''
            from model_wiki import Model_wiki as Model_wiki_ask
            modelwiki = Model_wiki_ask()
            
            # take place from filename if present
            if os.path.basename(filename).find(override_key)>0:
                street_wdid = self.get_placewikidatalist_from_string(
                    os.path.basename(filename))[0]
            elif os.path.isfile(street):
                if geo_dict is None:
                    self.logger.error(
                        filename + '  must have coordinates for search in geodata, or set --street')
                    return None
                regions_filepath = street
                from model_geo import Model_Geo as Model_geo_ask
                modelgeo = Model_geo_ask()
                if 'dest_lat' in geo_dict and 'dest_lon' in geo_dict:
                    lat=geo_dict.get("dest_lat")
                    lon=geo_dict.get("dest_lon")
                else:
                    lat=geo_dict.get("lat")
                    lon=geo_dict.get("lon")
                street_wdid = modelgeo.identify_deodata(lat, lon, regions_filepath, geodata_attribute)
                if street_wdid is None:
                    msg = f'file:{regions_filepath} https://geohack.toolforge.org/geohack.php?params={lat};{lon}_type:camera'
                    self.logger.error(filename.ljust(
                        40) + ' not found location in '+msg+'')
                    return None
                #street_wd = modelwiki.get_wikidata_simplified(street_wdid)
            else:
                # take street from user input

                street_wdid = modelwiki.wikidata_input2id(street)
                if street is not None:
                    assert street_wdid is not None
            return street_wdid


    def make_image_texts_vehicle(self, filename, vehicle, model, number, street=None, system=None,  route=None, country=None, line=None, facing=None, colors=None, operator=None, operator_vehicle_category=None, secondary_wikidata_ids=None, digital_number=None) -> dict:
        assert os.path.isfile(filename)

        from model_wiki import Model_wiki as Model_wiki_ask
        modelwiki = Model_wiki_ask()
        categories = set()
        need_create_categories = list()

        vehicle_names = {'ru': {'tram': 'трамвай', 'trolleybus': 'троллейбус',
                                'bus': 'автобус', 'train': 'поезд', 'locomotive': 'локомотив', 'auto': 'автомобиль', 'plane': 'самолёт'}}
        wikidata_4_structured_data = set()
        train_synonims = ['train', 'locomotive', 'emu', 'dmu']

        # assert facing in ('Left','Right',None)

        # obtain exif
        dt_obj = self.image2datetime(filename)
        geo_dict = self.image2coords(filename)

        if model is not None:
            model_wdid = modelwiki.wikidata_input2id(model)
            model_wd = modelwiki.get_wikidata_simplified(model_wdid)
            model_names = model_wd["labels"]
            wikidata_4_structured_data.add(model_wd['id'])

        # STREET
        # if street - vector file path: get street wikidata code by point in polygon
        if street is not None:
            street_wdid = self.get_place_from_input(filename,street,geo_dict)
            
            if street_wdid is None:
                self.logger.error('not set place/street')
                return None
            street_wd = modelwiki.get_wikidata_simplified(street_wdid)
            street_names = street_wd["labels"]
            wikidata_4_structured_data.add(street_wd['id'])
            # add city/district to structured data
            city_wd = modelwiki.get_territorial_entity(street_wd)
            if city_wd is None:
                msg = 'https://www.wikidata.org/wiki/' + \
                    str(street_wdid) + ' must have territorial entity'
                self.logger.error(msg)
                return None

            wikidata_4_structured_data.add(city_wd['id'])
        
        # Optionaly obtain country from gpkg file if country parameter is path to vector file (.gpkg)
        if os.path.isfile(country):
            country = self.get_place_from_input(filename,country,geo_dict,override_key='_location',geodata_attribute='name:en')
            if country is None:
                #place should taken from gpkg, but not found
                return None  

                
        # TAKEN ON LOCATION
        # search filename for pattern "_locationMoscow-Oblast"
        import re
        l=None
        regex = "_location(.*?)[_.\b]"
        test_str = os.path.basename(filename)

        matches = re.finditer(regex, test_str, re.MULTILINE)
        for match in matches:
            l = match.group()[9:-1].replace('-',' ').title()
        if l == 'location':
            l = None
        if l is not None: country=l
        del l

        # ROUTE
        if route is None:
            # extract route "34" from 3216_20070112_052_r34.jpg
            import re
            regex = "_r(.*?)[_.\b]"
            test_str = os.path.basename(filename)

            matches = re.finditer(regex, test_str, re.MULTILINE)
            for match in matches:
                result = match.group()[2:-1]
                if 'eplace' in result:
                    continue
                route = result
                del result
            if route == 'z':
                route = None

        # DIGITAL_NUMBER
        if digital_number is None:
            # extract number "1456" from 2TE10M-1456_20230122_444_dn1456.jpg
            import re
            regex = "_n(.*?)[_.\b]"
            test_str = os.path.basename(filename)

            matches = re.finditer(regex, test_str, re.MULTILINE)
            for match in matches:
                digital_number = match.group()[2:-1]

        # OPERATOR
        if operator is not None:

            operator_wd = modelwiki.get_wikidata_simplified(modelwiki.wikidata_input2id(operator))
            wikidata_4_structured_data.add(operator_wd['id'])
        # OPERATOR VEHICLE CATEGORY
        if operator_vehicle_category is not None:
            categories.add(operator_vehicle_category.replace('Category:',''))


        # SYSTEM
        if system=='FROMFILENAME':
            # extract system "Q123456" from 16666_20070707_000_systemQ123456.jpg
            import re
            regex = "_system(.*?)[_.\b]"
            test_str = os.path.basename(filename)

            matches = re.finditer(regex, test_str, re.MULTILINE)
            for match in matches:
                system = match.group()[7:-1]
        system_names = dict()
        if system is not None:
            system_wdid = modelwiki.wikidata_input2id(system)
            system_wd = modelwiki.get_wikidata_simplified(system_wdid)

            system_names = system_wd["labels"]
            # GET "RZD" from "Russian Railways"
            if 'P1813' in system_wd['claims']:
                for abbr_record in system_wd['claims']['P1813']:
                    system_names[abbr_record['language']
                                 ] = abbr_record['value']

            wikidata_4_structured_data.add(system_wd['id'])
            system_territorial_entity = modelwiki.get_territorial_entity(
                system_wd)
            if system_territorial_entity is not None:
                city_name_en = system_territorial_entity['labels']['en'] or ''
                city_name_ru = system_territorial_entity['labels']['ru'] or ''
            else:
                city_name_en = None
                city_name_ru = None

        elif system is None:

            city_wd = modelwiki.get_territorial_entity(street_wd)
            try:
                city_name_en = city_wd['labels']['en']
                city_name_ru = city_wd['labels']['ru']
            except:
                raise ValueError('object https://www.wikidata.org/wiki/' +
                                 city_wd['id']+' must has name ru and name en')
            if city_wd['id'] not in wikidata_4_structured_data:
                wikidata_4_structured_data.add(city_wd['id'])

        # LINE
        line_wdid = None
        line_wd = None
        line_names = dict()
        if line is not None:
            line_wdid = self.take_user_wikidata_id(line)
            line_wd = modelwiki.get_wikidata_simplified(line_wdid)

            line_names = line_wd["labels"]

            wikidata_4_structured_data.add(line_wdid)
        elif line is None and vehicle in train_synonims:
            # GET RAILWAY LINE FROM WIKIDATA
            if 'P81' in street_wd['claims'] and len(street_wd['claims']['P81']) == 1:
                line_wd = modelwiki.get_wikidata_simplified(
                    street_wd['claims']['P81'][0]['value'])
                line_wdid = line_wd['id']

        # trollybus garage numbers. extract 3213 from 3213_20060702_162.jpg
        if number == 'BEFORE_UNDERSCORE':
            number = os.path.basename(
                filename)[0:os.path.basename(filename).find('_')]

        filename_base = os.path.splitext(os.path.basename(filename))[0]
        filename_extension = os.path.splitext(os.path.basename(filename))[1]

        placenames = {'ru': list(), 'en': list()}

        if 'en' in line_names:
            if len(line_names['en']) > 0:
                placenames['en'].append(line_names['en'])
        if 'en' in street_names:
            if street_names['en'] != '':
                placenames['en'].append(street_names['en'])

        if vehicle not in train_synonims:
            objectname_en = '{city} {transport} {number}'.format(
                transport=vehicle,
                city=city_name_en,
                model=model_names['en'],
                number=number
            )

            objectname_ru = '{city}, {transport} {model} {number}'.format(
                city=city_name_ru,
                transport=vehicle_names['ru'][vehicle],
                model=model_names.get('ru', model_names['en']),
                number=number
            )
            commons_filename = '{city} {transport} {number} {dt} {place} {model}{extension}'.format(
                city=city_name_en,
                transport=vehicle,
                number=number,
                dt=dt_obj.strftime("%Y-%m %s"),
                place=' '.join(placenames['en']),
                model=model_names['en'],
                extension=filename_extension)

            # filename for Moscow Trolleybus
            if system_wdid == 'Q4304313':
                commons_filename = '{city} {transport} {model} {number} {dt} {place}{extension}'.format(
                    city=city_name_en,
                    transport=vehicle,
                    number=number,
                    dt=dt_obj.strftime("%Y-%m %s"),
                    place=' '.join(placenames['en']),
                    model=model_names['en'],
                    extension=filename_extension)

            # commons_filename = objectname_en + " " +dt_obj.strftime("%Y-%m %s") + model_names['en'] + ' '+ ' '.join(placenames['en'])+ ' ' + filename_extension
        elif vehicle in train_synonims:
            assert street_names is not None or line_names is not None
            if 'en' not in system_names:
                system_names['en'] = ''
            if 'ru' not in system_names:
                system_names['ru'] = ''

            # {model} removed
            number_lat = translit(number, "ru", reversed=True)

            objectname_en = '{system}{number_lat}'.format(
                system=system_names['en']+' ',
                city=city_name_en,
                model=model_names['en'],
                number_lat=number_lat,
                place=' '.join(placenames['en'])
            )
            commons_filename = '{system}{number_lat} {dt} {place} {timestamp}{extension}'.format(
                system=system_names['en']+' ',
                number_lat=number_lat,
                dt=dt_obj.strftime("%Y-%m"),
                place=' '.join(placenames['en']),
                timestamp=dt_obj.strftime("%s"),
                extension=filename_extension
            )

            objectname_ru = '{system}{number}'.format(
                system=system_names['ru']+' ',
                transport=vehicle_names['ru'][vehicle],
                model=model_names.get('ru', model_names['en']),
                number=number
            )

            locomotive_inscription = number_lat
            locomotive_railway_code = system_names['en']

        commons_filename = commons_filename.replace("/", " drob ")

        text = ''

        text = """== {{int:filedesc}} ==
{{Information
|description="""
        captions = dict()
        assert 'en' in street_names,  'https://www.wikidata.org/wiki/' + \
            street_wdid + ' must have english name'
        captions['en'] = objectname_en + ' at ' + street_names['en']
        if route is not None:
            captions['en'] += ' Line '+route
        if line_wdid is not None:
            assert 'en' in modelwiki.get_wikidata_simplified(line_wdid)[
                'labels'], 'object https://www.wikidata.org/wiki/' + line_wdid + ' must has name en'
            captions['en'] += ' ' + \
                modelwiki.get_wikidata_simplified(line_wdid)['labels']['en']
        text += "{{en|1=" + captions['en'] + '}}'+"\n"

        captions['ru'] = objectname_ru + ' на ' +  \
            street_names['ru'].replace(
                'Улица', 'улица').replace('Проспект', 'проспект')
        if route is not None:
            captions['ru'] += ' Маршрут '+route
        if line_wdid is not None:
            captions['ru'] += ' ' + \
                modelwiki.get_wikidata_simplified(line_wdid)['labels']['ru']
        text += "{{ru|1=" + captions['ru'] + '}}'+"\n"

        if model is not None:
            text += " {{on Wikidata|" + model_wdid.split('#')[0] + "}}\n"
        text += " {{on Wikidata|" + street_wdid + "}}\n"

        if type(secondary_wikidata_ids) == list and len(secondary_wikidata_ids) > 0:
            for wdid in secondary_wikidata_ids:
                text += " {{on Wikidata|" + wdid + "}}\n"
                heritage_id = None
                heritage_id = modelwiki.get_heritage_id(wdid)
                if heritage_id is not None:
                    text += "{{Cultural Heritage Russia|" + heritage_id + "}}"
                    today = datetime.today()
                    if today.strftime('%Y-%m') == '2023-09':
                        text += "{{Wiki Loves Monuments 2023|1=ru}}"
        text += "\n"
        text += self.get_date_information_part(dt_obj, country)
        text += "}}\n"
        tech_description, tech_categories = self.get_tech_description(filename, geo_dict)
        assert None not in tech_categories, 'None value in '+str(tech_categories)
        text +=tech_description+"\n"
        categories.update(tech_categories)
        

        transports = {
            'tram': 'Trams',
            'trolleybus': 'Trolleybuses',
            'bus': 'Buses',
            'train': 'Rail vehicles',
            'locomotive': 'Locomotives',
            'auto': 'Automobiles'
        }
        transports_color = {
            'tram': 'Trams',
            'trolleybus': 'Trolleybuses',
            'bus': 'Buses',
            'train': 'Rail vehicles',
            'locomotive': 'Rail vehicles',
            'auto': 'Automobiles'
        }
        transports_wikidata = {
            'tram': 'Q3407658',
            'trolleybus': 'Q5639',
            'bus': 'Q5638',
            'train': 'Q1414135',
            'locomotive': 'Q93301',
            'auto': 'Q1420'
        
        
        }

        if route is not None:
            cat="{transports} on route {route} in {city}".format(
                transports=transports[vehicle],
                route=route,
                city=city_name_en)
            cat_content='''
{{GeoGroup}}
[[Category:$vehicle routes designated $route|$city_name_en]]
[[Category:$transports in $city_name_en by route|$route]]'''
            cat_content=cat_content.replace('$vehicle',vehicle.title())
            cat_content=cat_content.replace('$route',route)
            cat_content=cat_content.replace('$transports',transports[vehicle])
            cat_content=cat_content.replace('$city_name_en',city_name_en)
            
            need_create_categories.append({'name':cat,'content':cat_content})
            categories.add(cat)
        
        if 'system_wd' in locals():
            if vehicle not in train_synonims:
                categories.add(system_wd['commons'])

        cat = 'Photographs by {photographer}/{country}/{transport}'
        cat = cat.format(photographer=self.photographer,
                         country=country,
                         transport=transports[vehicle].lower().capitalize())
        categories.add(cat)
        cat_content='''{{Usercat}}
[[Category:Photographs_by_'''+self.photographer+'/'+country+''']]'''
        modelwiki.create_category(
                cat, cat_content)
        cat = 'Photographs by {photographer}/{country}'
        cat = cat.format(photographer=self.photographer,
                         country=country,
                         transport=transports[vehicle].lower().capitalize())
        cat_content='''{{Usercat}}
[[Category:Photographs_by_'''+self.photographer+''']]
[[Category:Photographs_of_'''+country+'''_by_photographer]]'''
        modelwiki.create_category(
                cat, cat_content)


        trains_on_line_cat = None
        trains_on_station_cat = None

        if vehicle in train_synonims:
            trains_on_station_cat = None
            trains_on_station_cat = modelwiki.search_commonscat_by_2_wikidata(
                street_wdid, 'Q870')
            if trains_on_station_cat is None:
                if street_wd['commons'] is not None:
                    cat = 'Category:Trains at '+street_wd['commons']
                    if modelwiki.is_category_exists(cat):
                        trains_on_station_cat = cat
                        del cat

            if line_wd is not None:
                trains_on_line_cat = modelwiki.search_commonscat_by_2_wikidata(
                    line_wdid, 'Q870')
                if trains_on_line_cat is None:
                    if line_wd['commons'] is not None:
                        cat = 'Category:Trains on '+line_wd['commons']
                        if modelwiki.is_category_exists(cat):
                            trains_on_line_cat = cat
                            del cat

            # TRAINS AT STATION
            if trains_on_station_cat is not None:
                categories.add(trains_on_station_cat)
                if line_wdid is not None:
                    wikidata_4_structured_data.add(line_wdid)
                wikidata_4_structured_data.add(street_wdid)
            # TRAINS ON LINE
            elif trains_on_line_cat is not None:
                categories.add(trains_on_line_cat)
                if line_wdid is not None:
                    wikidata_4_structured_data.add(line_wdid)
                wikidata_4_structured_data.add(street_wdid)
            if trains_on_station_cat is None:
                # STATION
                if street_wd['commons'] is None:
                    self.logger.error('https://www.wikidata.org/wiki/' +
                                      street_wd['id'] + ' must have commons category')
                    return None
                categories.add(street_wd['commons'])
                wikidata_4_structured_data.add(street_wdid)
                # LINE
                if line_wd is not None:
                    wikidata_4_structured_data.add(line_wd['id'])
                    if trains_on_line_cat is None and line_wd['commons'] is not None:
                        categories.add(line_wd['commons'])

        else:
            if line_wd is not None:
                if line_wd['commons'] is not None:
                    categories.add(line_wd['commons'])
            if street_wd is not None and 'commons' in street_wd:
                categories.add(street_wd['commons'])

        assert None not in wikidata_4_structured_data, 'empty value added to structured data set:' + \
            str(' '.join(list(wikidata_4_structured_data)))

        # locale.setlocale(locale.LC_ALL, 'en_GB')
        if vehicle == 'tram':
            catname = "Railway photographs taken on "+dt_obj.strftime("%Y-%m-%d")
            categories.add(catname)

        if vehicle in train_synonims:
            catname = "Railway photographs taken on " + \
                dt_obj.strftime("%Y-%m-%d")
            categories.add(catname)
            modelwiki.create_category(
                catname, '{{Railway photographs taken on navbox}}')
            if isinstance(country, str) and len(country) > 3:
                catname = dt_obj.strftime("%B %Y") + \
                    " in rail transport in "+country
                categories.add(catname)
                category_content = '{{GeoGroup|level=2}}{{railtransportmonth-country|'+dt_obj.strftime(
                    "%Y")[0:3]+'|'+dt_obj.strftime("%Y")[-1:]+'|'+dt_obj.strftime("%m")+'|'+country+'}}'
                modelwiki.create_category(catname, category_content)



        
                
        # do not add facing category if this is interior
        if 'Q60998096' in secondary_wikidata_ids:
            facing = None
        if facing is not None:
            facing = facing.strip().capitalize()
            # assert facing.strip().upper() in ('LEFT','RIGHT')

            if facing == 'Left':
                text += "[[Category:"+transports[vehicle] + \
                    " facing " + facing.lower() + "]]\n"
            if facing == 'Right':
                text += "[[Category:"+transports[vehicle] + \
                    " facing " + facing.lower() + "]]\n"
            if facing == 'Side':
                text += "[[Category:Side views of " + \
                    transports[vehicle].lower()+"]]\n"
            if facing == 'Rear':
                text += "[[Category:Rear views of " + \
                    transports[vehicle].lower()+"]]\n"
            if facing == 'Front':
                text += "[[Category:Front views of " + \
                    transports[vehicle].lower()+"]]\n"
            if facing == 'Rear three-quarter'.capitalize():
                text += "[[Category:Rear three-quarter views of " + \
                    transports[vehicle].lower()+"]]\n"
            if facing == 'Three-quarter'.capitalize():
                text += "[[Category:Three-quarter views of " + \
                    transports[vehicle].lower()+"]]\n"

            if facing == 'Left':
                wikidata_4_structured_data.add('Q119570753')
            if facing == 'Right':
                wikidata_4_structured_data.add('Q119570670')
            if facing == 'Front':
                wikidata_4_structured_data.add('Q1972238')

        if colors is None and 'color' in os.path.basename(filename):
            colors = self.get_colorlist_from_string(os.path.basename(filename))
        if colors is not None:
            colorname = ''
            if colors[0].upper() == 'RZDGREEN':
                text += "[[Category:Trains in Russian railways green livery]]\n".format(
                    transports=transports_color[vehicle].lower(),
                    colorname=colorname)
            elif colors[0].upper() == 'RZD':
                text += "[[Category:Trains in Russian Railways livery]]\n".format(
                    transports=transports_color[vehicle].lower(),
                    colorname=colorname)
            else:
                colors.sort()
                colorname = ' and '.join(colors)
                colorname = colorname.lower().capitalize()
                text += "[[Category:{colorname} {transports}]]\n".format(
                    transports=transports_color[vehicle].lower(),
                    colorname=colorname)

        # vehicle to wikidata
            vehicles_wikidata = {"trolleybus": "Q5639", "bus": "Q5638",
                                 "tram": "Q3407658", "auto": "Q1420", "locomotive": "Q93301", "train": "Q870"}
            if vehicle in vehicles_wikidata:
                wikidata_4_structured_data.add(vehicles_wikidata[vehicle])
            if vehicle in train_synonims:
                wikidata_4_structured_data.add(vehicles_wikidata['train'])

        # number
        has_category_for_this_vehicle = False
        if number is not None:
            number_filtered = number
            if '-' in number_filtered:
                number_filtered = number_filtered[number_filtered.index(
                    '-')+1:]
            if digital_number is None:
                digital_number = number_filtered
        if number is not None and vehicle in ('bus','trolleybus','tram'):
            cat = f'{city_name_en} {vehicle} {number}'
            self.logger.info('search if exist optional category '+cat)
            if modelwiki.is_category_exists(cat):
                has_category_for_this_vehicle = True
                categories.add(cat)
        elif number is not None and vehicle in train_synonims:
            # search for category for this railway locomotive
            cat = f'{locomotive_railway_code} {locomotive_inscription}'
            if modelwiki.is_category_exists(cat):
                has_category_for_this_vehicle = True
                categories.add(cat)
            else:
                catname = "Number "+digital_number+" on rail vehicles"
                category_page_content = '{{NumbercategoryTrain|'+digital_number+'}}'
                modelwiki.create_category(catname, category_page_content)
                categories.add(catname)

                # upper category
                catname = 'Number '+digital_number+' on vehicles'
                category_page_content = '{{Numbercategory-vehicle|'+digital_number + \
                    '|vehicle|Number '+digital_number+' on objects|Vehicle}}'
                modelwiki.create_category(catname, category_page_content)

                # upper category
                catname = 'Number '+digital_number+' on objects'
                category_page_content = '{{Number on object|n='+digital_number+'}}'
                modelwiki.create_category(catname, category_page_content)
        # end of search category for this vehicle 
        
        if number is not None and vehicle == 'bus':
            catname = f'Number {digital_number} on buses'
            if not has_category_for_this_vehicle: categories.add(catname)
            modelwiki.create_number_on_vehicles_category(vehicle='bus', number=digital_number)
        elif number is not None and vehicle == 'trolleybus':
            catname = f'Number {digital_number} on trolleybuses'
            if not has_category_for_this_vehicle: categories.add(catname)
            modelwiki.create_number_on_vehicles_category(vehicle='trolleybus', number=digital_number)
        elif number is not None and vehicle == 'tram':
            catname="Trams with fleet number "+digital_number
            if not has_category_for_this_vehicle: categories.add(catname)
            category_page_content = '{{' + \
                f'Numbercategory-vehicle-fleet number|{digital_number}|Trams|Number {digital_number} on trams'+'|image=}}'
            modelwiki.create_category(catname, category_page_content)
        elif number is not None and vehicle != 'tram':
            pass

        if dt_obj is not None and vehicle not in train_synonims:
            catname = "{transports} in {country} photographed in {year}".format(
                transports=transports[vehicle],
                country=country,
                year=dt_obj.strftime("%Y"),
            )
            text += "[[Category:"+catname+"]]\n"
            if vehicle == 'trolleybus':
                category_page_content = "[[Category:{transports} photographed in {year}]]\n[[Category:{transports} photographed in {year}]]".format(
                    transports=transports[vehicle],
                    country=country,
                    year=dt_obj.strftime("%Y"),
                )

                modelwiki.create_category(catname, category_page_content)
        # MODEL
        # if dt_obj is not None and vehicle == 'trolleybus':
        # category for model. search for category like "ZIU-9 in Moscow"
        if not has_category_for_this_vehicle:
            cat = modelwiki.get_category_object_in_location(
                model_wd['id'], street_wd['id'], order=digital_number, verbose=True)
            if cat is not None:
                categories.add(cat)
            else:
                categories.add(model_wd["commons"] +
                               '|' + digital_number)
        
        # categories for secondary_wikidata_ids
        # search for geography categories using street like (ZIU-9 in Russia)

        if type(secondary_wikidata_ids) == list and len(secondary_wikidata_ids) > 0:
            for wdid in secondary_wikidata_ids:
                cat = modelwiki.get_category_object_in_location(
                    wdid, street_wdid, verbose=True)
                if cat is not None:
                    categories.add(cat)
                else:
                    wd_record = modelwiki.get_wikidata_simplified(wdid)
                    if wd_record is None:
                        return None
                    secondary_objects_should_have_commonscat = False
                    if secondary_objects_should_have_commonscat:
                        assert 'commons' in wd_record, 'https://www.wikidata.org/wiki/' + \
                            wdid + ' must have commons'
                        assert wd_record["commons"] is not None, 'https://www.wikidata.org/wiki/' + \
                            wdid + ' must have commons'

                    if 'commons' in wd_record and wd_record["commons"] is not None:
                       categories.add(wd_record['commons'])
        categories.discard(None)
        for catname in categories:
            
            assert catname is not None, 'none value in categories:' + str(categories)+' '+filename
            catname = catname.replace('Category:', '')
            text += "[[Category:"+catname+"]]" + "\n"

        assert None not in wikidata_4_structured_data, 'empty value added to structured data set:' + \
            str(' '.join(list(wikidata_4_structured_data)))
        return {"name": commons_filename, 
        "text": text,
                "structured_data_on_commons": list(wikidata_4_structured_data),
                "country":country,
                'captions': captions,
                'need_create_categories':need_create_categories,
                "dt_obj": dt_obj}

    def get_colorlist_from_string(self, test_str: str) -> list:
        # from string 2002_20031123__r32_colorgray_colorblue.jpg  returns [Gray,Blue]
        # 2002_20031123__r32_colorgray_colorblue.jpg

        import re
        # cut to . symbol if extsts
        test_str = test_str[0:test_str.index('.')]

        # split string by _
        parts = re.split('_+', test_str)

        lst = list()
        for part in parts:
            if part.startswith('color'):
                lst.append(part[5:].title())

        print(lst)
        return lst
    
    def get_replace_id_from_string(self, test_str: str) -> str:
        '''
        from string 12345_replace56911685.jpg returns M56911685
        '''
        import re
        # cut to . symbol if extsts
        test_str = test_str[0:test_str.index('.')]

        lst = re.findall(r'(replace\d+)', test_str)
        id=lst[0].replace('replace','')
        return id
    
    def get_wikidatalist_from_string(self, test_str: str) -> list:
        ''' from string 2002_20031123__r32_colorgray_colorblue_wikidataQ12345_wikidataAntonovka.jpg  returns [Q12345]
        # 2002_20031123__r32_colorgray_colorblue.jpg
        '''
        import re
        # cut to . symbol if extsts
        test_str = test_str[0:test_str.index('.')]

        lst = re.findall(r'(Q\d+)', test_str)

        return lst

    def get_placewikidatalist_from_string(self, test_str: str) -> list:
        # from string 2002_20031123__r32_colorgray_colorblue_locationQ12345_wikidataAntonovka.jpg  returns [Q12345]
        # 2002_20031123__r32_colorgray_colorblue.jpg

        import re
        # cut to . symbol if extsts
        test_str = test_str[0:test_str.index('.')]

        lst = re.findall(r'(placeQ\d+)', test_str)

        lst2 = list()
        for line in lst:
            lst2.append(line[5:])
        lst = lst2
        del lst2
        if 'placeQ' in test_str:
            assert lst[0].startswith('Q'), lst[0] + \
                ' get instead of wikidata id'

        return lst


        
    def get_date_information_part(self, dt_obj, taken_on_location):
        st = ''
        st += (
            """|date="""
            + "{{Taken on|"
            + dt_obj.isoformat()
            + "|location="
            + taken_on_location
            + "|source=EXIF}}"
            + "\n"
            +"""|source={{own}}
|author={{Creator:""" + self.photographer+"""}}"""
        )
        return st

    def get_tech_description(self, filename, geo_dict):
        text = ''
        if 'stitch' in filename:
            text = text + "{{Panorama}}" + "\n"

        if geo_dict is not None:
            st = (
                "{{Location dec|"
                + str(geo_dict.get("lat"))
                + "|"
                + str(geo_dict.get("lon"))
            )
            if "direction" in geo_dict:
                st += "|heading:" + str(geo_dict.get("direction"))
            st += "}}\n"
            text += st

            if "dest_lat" in geo_dict:
                st = (
                    "{{object location|"
                    + str(geo_dict.get("dest_lat"))
                    + "|"
                    + str(geo_dict.get("dest_lon"))
                    + "}}"
                    + "\n"
                )
                text += st
        camera_text, camera_categories = self.get_camera_text(filename)
        text += camera_text

        text = (
            text
            + '== {{int:license-header}} =='+"\n"+placejpgconfig.license+"\n\n"
        )
        categories = set()
        categories.update(camera_categories)


        if 'ShiftN' in filename:
            categories.add('Corrected with ShiftN')
        if 'stitch' in filename:
            categories.add('Photographs by ' + self.photographer + '/Stitched panoramics')
        categories.add('Uploaded with Placejpg')

        return text,categories




    def make_image_texts_simple(
        self, filename, wikidata, country='', rail='', secondary_wikidata_ids=list(), quick=False
    ) -> dict:
        # return file description texts
        # there is no excact 'city' in wikidata, use manual input cityname

        from model_wiki import Model_wiki as Model_wiki_ask
        modelwiki = Model_wiki_ask()

        need_create_categories = list()

        assert os.path.isfile(filename), 'not found '+filename

        categories = set()
        # obtain exif
        if not quick:
            dt_obj = self.image2datetime(filename)
            geo_dict = self.image2coords(filename)
        else:
            dt_obj = datetime.strptime(
                '1970:01:01 00:00:00', "%Y:%m:%d %H:%M:%S")
            geo_dict = None

        # Optionaly obtain wikidata from gpkg file if wikidata parameter is path to vector file (.gpkg)
        if os.path.isfile(wikidata):
            street=wikidata
            wikidata = self.get_place_from_input(filename,street,geo_dict)
            del street
            if wikidata is None:
                #place should taken from gpkg, but not found
                return None

        # Optionaly obtain country from gpkg file if country parameter is path to vector file (.gpkg)
        if os.path.isfile(country):
            country = self.get_place_from_input(filename,country,geo_dict,override_key='_location',geodata_attribute='name:en')
            if country is None:
                #place should taken from gpkg, but not found
                return None   
        
        # Optionaly obtain prefix from gpkg file
        prefix = ''
        if os.path.isfile('prefixes.gpkg'):
            prefix = self.get_place_from_input(filename,'prefixes.gpkg',geo_dict,override_key='_prefix',geodata_attribute='name:en') or ''
                
        wd_record = modelwiki.get_wikidata_simplified(wikidata)
        
        if wd_record["commons"] is None: 
            self.logger.error('https://www.wikidata.org/wiki/' + \
            wikidata + ' must have commons')
            return None

        instance_of_data = list()
        if 'P31' in wd_record['claims']:
            for i in wd_record['claims']['P31']:
                instance_of_data.append(
                    modelwiki.get_wikidata_simplified(i['value']))

        text = ""
        objectnames = {}
        objectname_long = {}
        objectnames_long = {}

        #rewrite label if not extst
        for lang in self.langs_primary:
            if lang not in wd_record['labels']:
                
                self.logger.error('object https://www.wikidata.org/wiki/' +
                    wd_record['id']+' must has name '+lang)
                return None
                wd_record['labels'][lang]=wd_record['labels']['en']
                #self.logger.error('object https://www.wikidata.org/wiki/' +
                #                 wd_record['id']+' must has name '+lang)
                #return None
            objectnames[lang] = wd_record['labels'][lang]
            objectname_long[lang] = objectnames[lang]

        for lang in self.langs_optional:
            if lang in wd_record['labels']:
                objectnames[lang] = wd_record['labels'][lang]

        # BUILD DESCRIPTION FROM 'INSTANCE OF' NAMES
        #  
        if len(instance_of_data) > 0:
            for lang in self.langs_primary:
                for i in instance_of_data:
                    if lang not in i['labels']:
                        self.logger.error('object https://www.wikidata.org/wiki/' +
                                 i['id']+' must has name '+lang)
                        return None
                objectname_long[lang] = ', '.join(
                d['labels'][lang] for d in instance_of_data) + ' '+objectnames[lang]

            for lang in self.langs_optional:
                try:
                    objectnames_long[lang] = ', '.join(
                        d['labels'][lang] for d in instance_of_data) + ' '+objectnames[lang]
                except:
                    pass
        else:
            for lang in self.langs_primary:
                if lang in objectnames:  objectname_long[lang] = objectnames[lang]
            for lang in self.langs_optional:
                if lang in objectnames:   objectname_long[lang] = objectnames[lang]

        """== {{int:filedesc}} ==
{{Information
|description={{en|1=2nd Baumanskaya Street 1 k1}}{{ru|1=Вторая Бауманская улица дом 1 К1}} {{on Wikidata|Q86663303}}  {{Building address|Country=RU|Street name=2-я Бауманская улица|House number=1 К1}}  
|source={{own}}
|author={{Creator:Artem Svetlov}}
|date={{According to Exif data|2022-07-03|location=Moscow}}
}}

{{Location|55.769326012498155|37.68742327500131}}
{{Taken with|Pentax K10D|sf=1|own=1}}

{{Photo Information
 |Model                 = Olympus mju II
 |ISO                   = 200
 |Lens                  = 
 |Focal length          = 35
 |Focal length 35mm     = 35
 |Support               = freehand
 |Film                  = Kodak Gold 200
 |Developer             = C41
 }}
 
    == {{int:license-header}} ==
    {{self|cc-by-sa-4.0|author=Артём Светлов}}

    [[Category:2nd Baumanskaya Street 1 k1]]
    [[Category:Photographs by Artem Svetlov/Moscow]]

    """
        st = """== {{int:filedesc}} ==
{{Information
|description="""
        for lang in self.langs_primary:
            st += "{{"+lang+"|1=" + objectname_long[lang] + "}} \n"

        for lang in self.langs_optional:
            if lang in objectnames_long:
                st += "{{"+lang+"|1=" + objectnames_long[lang] + "}} \n"

        st += " {{on Wikidata|" + wikidata + "}}\n"
        if len(secondary_wikidata_ids) > 0:
            for secondary_wikidata_id in secondary_wikidata_ids:
                if secondary_wikidata_id == wikidata: continue
                st += " {{on Wikidata|" + secondary_wikidata_id + "}}\n"
            
        # CULTURAL HERITAGE
        # if main object is cultural heritage: insert special templates
        heritage_id = None
        heritage_id = modelwiki.get_heritage_id(wikidata)
        if heritage_id is not None:
            st += "{{Cultural Heritage Russia|" + heritage_id + "}}"
            today = datetime.today()
            if today.strftime('%Y-%m') == '2023-09':
                st += "{{Wiki Loves Monuments 2023|1=ru}}"
                

        st += self.get_date_information_part(dt_obj, country)
        st += "}}\n"

        text += st

        if not quick:
            tech_description, tech_categories = self.get_tech_description(filename, geo_dict)
            text = text + tech_description
        else:
            tech_categories = set()
            text = text + " >>>>> TECH TEMPLATES SKIPPED <<<<<<\n"
        del tech_description
        categories.update(tech_categories)

        # USERCAT BY THEME
        usercat_categories = set()
        
        # PHOTOS OF USER IN COUNTRY
        CategoryUserInCountry = ''
        CategoryUser = 'Photographs by '+self.photographer
        cat = 'Photographs by {photographer}/{country}'
        cat = cat.format(photographer=self.photographer,
                         country=country,
                        )           
        cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUser+''']]
[[Category:Photographs of '''+country+''' by photographer]]'''
        need_create_categories.append({'name':cat,'content':cat_content})
        CategoryUserInCountry = cat
        
        # PHOTOS OF USER IN COUNTRY WITH ARCHITECTURE STYLE
        
        #check is any wikidata object is building and it has architecture style with commons category
        prop='P149' #architecture style
        temp_wikidata_list = list()
        temp_wikidata_list = secondary_wikidata_ids+[wikidata]
        for wdid in temp_wikidata_list:
            wd=modelwiki.get_wikidata_simplified(wdid)
            if prop in wd['claims']:
                for claim in wd['claims'][prop]:
                    cat_for_claim=''
                    cat_for_claim = modelwiki.get_wikidata_simplified(claim['value'])['commons']    
                    cat_for_claim = f'{CategoryUserInCountry}/{cat_for_claim}'
                    cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUserInCountry+''']]'''
                    need_create_categories.append({'name':cat_for_claim,'content':cat_content})
                    usercat_categories.add(cat_for_claim)
                    del cat_for_claim
        
        # SUBCLASS OF ARCHITECTURAL ELEMENT
        temp_wikidata_list = list()
        temp_wikidata_list = secondary_wikidata_ids+[wikidata]
        for wdid in temp_wikidata_list:
            if modelwiki.is_subclass_of(wdid,'Q391414'):
                wd=modelwiki.get_wikidata_simplified(wdid)    
                cat_for_claim=''
                cat_for_claim = f'{CategoryUserInCountry}/Architectural elements'
                cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUser+'''/Architectural elements]]
[[Category:'''+CategoryUserInCountry+''']]'''
                need_create_categories.append({'name':cat_for_claim,'content':cat_content})
                usercat_categories.add(cat_for_claim)
                
                cat_for_claim = f'{CategoryUser}/Architectural elements'
                cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUser+''']]
'''
                need_create_categories.append({'name':cat_for_claim,'content':cat_content})                  
                del cat_for_claim
                
        # BUILING DATE START
        temp_wikidata_list = list()
        temp_wikidata_list = secondary_wikidata_ids+[wikidata]
        for wdid in temp_wikidata_list:
            # is this building but not transport infrastructure (station)
            if modelwiki.is_subclass_of_building(wdid) and not modelwiki.is_subclass_of(wdid,'Q376799'):
                wd=modelwiki.get_wikidata_simplified(wdid)
                prop=''
                if 'P1619' in wd['claims']: 
                    prop='P1619' #date of official opening
                elif  'P571' in wd['claims']:
                    prop='P571' #date of official opening
                else:
                    continue
                for claim in wd['claims'][prop]:
                    decade=claim['value'][:3]+'0'
                    cat_for_claim = f'{CategoryUserInCountry}/{decade}s architecture'
                    cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUserInCountry+''']]
[[Category:'''+CategoryUser+'/'+decade+'''s architecture]]
'''
                    need_create_categories.append({'name':cat_for_claim,'content':cat_content})
                    usercat_categories.add(cat_for_claim)
                    
                    cat_for_claim = f'{CategoryUser}/{decade}s architecture'
                    cat_content='''{{Usercat}}
{{GeoGroup}}
[[Category:'''+CategoryUser+''']]
'''
                    need_create_categories.append({'name':cat_for_claim,'content':cat_content})                  
                    del cat_for_claim
                        
        
        # END OF USERCAT CHECKS
        # when not found any special user categories: use CategoryUserInCountry       
        if len(usercat_categories)==0:
            usercat_categories.add(CategoryUserInCountry)
        
        categories.update(usercat_categories)
        # END USERCAT BY THEME
        
        if rail:
            text += "[[Category:Railway photographs taken on " + \
                dt_obj.strftime("%Y-%m-%d")+"]]" + "\n"
            if isinstance(country, str) and len(country) > 3:
                text += "[[Category:" + \
                    dt_obj.strftime("%B %Y") + \
                    " in rail transport in "+country+"]]" + "\n"

            
        if len(secondary_wikidata_ids) < 1:
            text = text + "[[Category:" + wd_record["commons"] + "]]" + "\n"
        else:
            text = text + "[[Category:" + wd_record["commons"] + "]]" + "\n"
            for wdid in secondary_wikidata_ids:
                cat = modelwiki.get_category_object_in_location(
                    wdid, wikidata, verbose=True)
                if cat is not None:
                    categories.add(cat)
                else:
                    wd_record = modelwiki.get_wikidata_simplified(wdid)
                    if wd_record.get('commons',None) is not None:
                        categories.add(wd_record["commons"])

                    
        for catname in categories:
            catname = catname.replace('Category:', '')
            text += "[[Category:"+catname+"]]" + "\n"

        commons_filename = self.commons_filename(
            filename, objectnames, wikidata, dt_obj, add_administrative_name=False, prefix=prefix)

        return {"name": commons_filename, 
                "text": text, 
                "dt_obj": dt_obj,
                "country":country,
                "need_create_categories":need_create_categories,
                "wikidata":wikidata}

    def commons_filename(self, filename, objectnames, wikidata, dt_obj, add_administrative_name=True, prefix='') -> str:
        # file name on commons

        from model_wiki import Model_wiki as Model_wiki_ask
        modelwiki = Model_wiki_ask()

        filename_base = os.path.splitext(os.path.basename(filename))[0]
        filename_extension = os.path.splitext(os.path.basename(filename))[1]
        # if this is building: try get machine-reading address from https://www.wikidata.org/wiki/Property:P669
        building_info = modelwiki.get_building_record_wikidata(
            wikidata, stop_on_error=False)
        if building_info is not None:

            objectnames['en'] = (
                building_info["addr:street:en"]
                + " "
                + building_info["addr:housenumber:en"]
            )
        commons_filename = ''
        
        if prefix != '': commons_filename = f"{prefix}_"

        

        commons_filename = (
            commons_filename + objectnames['en'] + " " +
            dt_obj.strftime("%Y-%m %s") + filename_extension
        )
        commons_filename = commons_filename.replace("/", " drob ")


        # add district name to file name
        if add_administrative_name:
            try:
                administrative_name = modelwiki.get_wikidata_simplified(modelwiki.get_upper_location_wdid(
                    modelwiki.get_wikidata_simplified(wikidata)))['labels']['en']
                commons_filename = administrative_name + '_'+commons_filename
            except:
                pass

        
        return commons_filename

    def take_user_wikidata_id(self, wdid) -> str:
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        # parse user input wikidata string.
        # it may be wikidata id, wikidata uri, string.
        # call search if need
        # return valid wikidata id
        if self.is_wikidata_id(wdid):
            result_wdid = wdid
        else:
            result_wdid = self.search_wikidata_by_string(
                wdid, stop_on_error=True)

        return result_wdid

    def get_shutterstock_desc(self, wikidata_list, filename, city, date=None) -> str:
        # https://support.submit.shutterstock.com/s/article/How-do-I-include-metadata-with-my-content?language=en_US
        '''
        Column A: Filename
Column B: Description
Column C: Keywords (separated by commas)
Column D: Categories ( 1 or 2, separated by commas, must be selected from this list)
Column E*: Illustration (Yes or No)
Column F*: Mature Content (Yes or No)
Column G*: Editorial (Yes or No)

he Illustration , Mature Content, and Editorial tags are optional and can be included or excluded from your CSV 
 Think of your title as a news headline and try to answer the main questions of: Who, What, When, Where, and Why. Be descriptive and use words that capture the emotion or mood of the image.
 Keywords must be in English, however, exceptions are made for scientific Latin names of plants and animals, names of places, and foreign terms or phrases commonly used in the English language.


Kaliningrad, Russia - August 28 2021: Tram car Tatra KT4 in city streets, in red color


        '''

        from model_wiki import Model_wiki
        modelwiki = Model_wiki()

        desc = {
            'Filename': filename,
            'Description': '',
            'Keywords': '',
            'Categories': '',
            'Editorial': 'Yes',
        }
        keywords = list()

        objects_wikidata = list()
        for obj_wdid in wikidata_list:
            obj_wdid = modelwiki.wikidata_input2id(obj_wdid)
            obj_wd = modelwiki.get_wikidata_simplified(obj_wdid)
            objects_wikidata.append(obj_wd)

        if self.is_wikidata_id(city):
            city_wdid = city
        else:
            city_wdid = self.search_wikidata_by_string(
                city, stop_on_error=True)
        city_wd = modelwiki.get_wikidata_simplified(city_wdid)

        # get country, only actual values. key --all returns historical values
        cmd = ['wd', 'claims', city_wdid, 'P17', '--json']
        response = subprocess.run(cmd, capture_output=True)
        country_json = json.loads(response.stdout.decode())
        country_wdid = country_json[0]
        country_wd = modelwiki.get_wikidata_simplified(country_wdid)

        try:
            dt_obj = self.image2datetime(filename)
        except:
            assert date is not None, 'in image '+filename + \
                'date can not be read from exif, need set date in --date yyyy-mm-dd'
            dt_obj = datetime.strptime(date, "%Y-%m-%d")

        object_captions = list()
        for obj_wd in objects_wikidata:
            object_captions.append(obj_wd['labels']['en'])

        d = '{city}, {country} - {date}: {caption}'.format(
            city=city_wd['labels']['en'],
            country=country_wd["labels"]["en"],
            date=dt_obj.strftime("%B %-d %Y"),
            caption=' '.join(object_captions)
        )

        for obj_wd in objects_wikidata:
            keywords.append(obj_wd['labels']['en'])
            aliases = obj_wd['aliases'].get('en', None)
            if type(aliases) == list and len(aliases) > 0:
                keywords += aliases

        keywords.append(city_wd['labels']['en'])
        keywords.append(city_wd['labels']['ru'])
        keywords.append(country_wd["labels"]["ru"])

        return d, keywords

    def get_camera_text(self, filename) -> list:
        st = ''
        categories = set()
        image_exif = self.image2camera_params(filename)
        lens_invalid_names=('0.0 mm f/0.0',)
        cameramodels_dict = {
                    'Pentax corporation PENTAX K10D': 'Pentax K10D',
                    'Pentax PENTAX K-r': 'Pentax K-r',
                    'Gopro HERO8 Black': 'GoPro Hero8 Black',
                    'Samsung SM-G7810': 'Samsung Galaxy S20 FE 5G',
                    'Olympus imaging corp.': 'Olympus',
                    'Nikon corporation NIKON': 'Nikon',
                    'Panasonic': 'Panasonic Lumix',
                    'Hmd global Nokia 5.3': 'Nokia 5.3',
                    'COOLPIX':'Coolpix',
                    'Fujifilm FinePix REAL 3D W3':'Fujifilm FinePix Real 3D W3',
                    'Ricoh RICOH THETA S':'Ricoh Theta S'
                }
        lensmodel_dict = {
                    'OLYMPUS M.12-40mm F2.8': 'Olympus M.Zuiko Digital ED 12-40mm f/2.8 PRO',
                    'smc PENTAX-DA 35mm F2.4 AL': 'SMC Pentax-DA 35mm F2.4',
                    'smc PENTAX-DA 14mm F2.8 EDIF': 'SMC Pentax DA 14 mm f/2.8 ED IF',
                }
        lens = None
        if image_exif.get("make") is not None and image_exif.get("model") is not None:
            if image_exif.get("make") != "" and image_exif.get("model") != "":
                make = image_exif.get("make").strip()
                model = image_exif.get("model").strip()
                make = make.capitalize()
                st = "{{Taken with|" + make + " " + model + "|sf=1|own=1}}" + "\n"

                st += '{{Photo Information|Model = ' + make + " " + model
                if image_exif.get("lensmodel", '') != "" and image_exif.get("lensmodel", '') != "":
                    lens = image_exif.get("lensmodel")
                    if lens in lens_invalid_names:
                        lens = None
                if lens is not None:
                    st += '|Lens = ' + image_exif.get("lensmodel")

                if image_exif.get("fnumber", '') != "" and image_exif.get("fnumber", '') != "" and int(image_exif.get("fnumber", 0)) != 0:
                    st += '|Aperture = f/' + str(image_exif.get("fnumber"))
                    categories.add(
                        'F-number f/'+str(image_exif.get("fnumber"))[0:5])
                if image_exif.get("'focallengthin35mmformat'", '') != "" and image_exif.get("'focallengthin35mmformat'", '') != "":
                    st += '|Focal length 35mm = f/' + \
                        str(image_exif.get("'focallengthin35mmformat'"))
                st += '}}' + "\n"


                if image_exif.get('usepanoramaviewer')==True: st += "{{Pano360}}"+ "\n"
                if image_exif.get("focallength", '') != "" and image_exif.get("focallength", '') != "" and int(image_exif.get("focallength", 0)) != 0:
                    categories.add(
                        'Lens focal length '+str(image_exif.get("focallength"))+' mm')

                if image_exif.get("iso", '') != "" and image_exif.get("iso", '') != "": 
                    try:
                        if int(image_exif.get("iso",0))>49:
                            try:
                                categories.add(
                                'ISO speed rating '+str(round(float(str(image_exif.get("iso")))))+'')
                            except:
                                self.logger.info('ISO value is bad:'+str(image_exif.get("iso", '')))
                    except:
                        pass

                for camerastring in cameramodels_dict.keys():
                    if camerastring in st:
                        st = st.replace(
                            camerastring, cameramodels_dict[camerastring])

                # lens quess
                if lens is not None:
                    st += "{{Taken with|" + lens.replace(
                        '[', '').replace(']', '').replace('f/ ', 'f/') + "|sf=1|own=1}}" + "\n"

                for lensstring in lensmodel_dict.keys():
                    if lensstring in st:
                        st = st.replace(lensstring, lensmodel_dict[lensstring])

                st = st.replace('Canon Canon', 'Canon')

                return st, categories
        else:
            return '', categories

    def image2camera_params_0(self, path):
        with open(path, "rb") as image_file:
            image_exif = Image(image_file)
        return image_exif

    def image2camera_params(self, path):
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(path)
            metadata = metadata[0]

            new_metadata = dict()
            for k, v in metadata.items():
                if ':' not in k:
                    continue
                new_metadata[k.split(':')[1].lower()] = v
            metadata = new_metadata
            return metadata
        except:
            self.logger.info(
                'error while call python exifread. Try get EXIF by call exifread executable')

            cmd = [self.exiftool_path, path, '-json', '-n']
            response = subprocess.run(cmd, capture_output=True)
            metadata = json.loads(response.stdout.decode())

            metadata = metadata[0]

            new_metadata = dict()
            for k, v in metadata.items():
                new_metadata[k.lower()] = v
            metadata = new_metadata

            return metadata

    def check_exif_valid(self, path):
        if path.lower().endswith('.stl'):
            return True

        cmd = [self.exiftool_path, path, "-datetimeoriginal", "-csv"]
        process = subprocess.run(cmd, stdout=subprocess.DEVNULL)

        if process.returncode == 0:
            return True
        else:
            return False

    def check_extension_valid(self, filepath) -> bool:
        ext = os.path.splitext(filepath)[1].lower()[1:]
        allowed = ['tiff', 'tif', 'png', 'gif', 'jpg', 'jpeg', 'webp', 'xcf', 'mid', 'ogg', 'ogv',
                   'svg', 'djvu', 'stl', 'oga', 'flac', 'opus', 'wav', 'webm','mp4','mov', 'mp3', 'midi', 'mpg', 'mpeg']
        if ext in allowed:
            return True
        return False

    def image2datetime(self, path):
    
        def get_datetime_from_string(s):
            # find the substring that matches the format YYYYMMDD_HHMMSS
            # assume it is always 15 characters long and starts with a digit

            for i in range(len(s) - 15):
                if s[i].isdigit():
                    date_str = s[i:i+15]
                    print('test '+date_str)
                    try:
                        datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                        # Valid date string
                        break
                    except ValueError:
                        pass
                        #go next char
                    
            # use datetime.strptime() to convert the substring to a datetime object
            date_obj = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            return date_obj

        with open(path, "rb") as image_file:
            if not path.lower().endswith('.stl'):
                try:
                    image_exif = Image(image_file)
                    
                    dt_str = image_exif.get("datetime_original", None)

                    dt_obj = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                except:
                    dt_obj = None
                    cmd = [self.exiftool_path, path, "-datetimeoriginal", "-csv"]
                    if path.lower().endswith(('.mp4','.mov')):
                        cmd = [self.exiftool_path, path, "-createdate", "-csv"]
                        self.logger.debug('video')

                    exiftool_text_result = subprocess.check_output(cmd)
                    tmp = exiftool_text_result.splitlines()[1].split(b",")
                    if len(tmp) > 1:
                        dt_str = tmp[1]
                        dt_obj = datetime.strptime(
                            dt_str.decode("UTF-8"), "%Y:%m:%d %H:%M:%S"
                        )
            elif path.lower().endswith('.stl'):
                dt_obj = None

            if dt_obj is None:
                dt_obj = get_datetime_from_string(os.path.basename(path))
                
               
                #except:
                #    print(f'file {path}: failed to get date, failed to read from start of filename')
                #    quit()

            if dt_obj is None:
                return None
            return dt_obj

    def image2coords(self, path):
        exiftool_metadata = self.image2camera_params(path)
        try:
            lat = round(float(exiftool_metadata.get('gpslatitude')), 6)
            lon = round(float(exiftool_metadata.get('gpslongitude')), 6)
        except:
            self.logger.warning('no coordinates in '+path)
            return None

        geo_dict = {}
        geo_dict = {"lat": lat, "lon": lon}
        if 'gpsimgdirection' in exiftool_metadata:
            geo_dict["direction"] = round(
                float(exiftool_metadata.get('gpsimgdirection')))

        if 'gpsdestlatitude' in exiftool_metadata:
            geo_dict["dest_lat"] = round(
                float(exiftool_metadata.get('gpsdestlatitude')), 6)
        if 'gpsdestlongitude' in exiftool_metadata:
            geo_dict["dest_lon"] = round(
                float(exiftool_metadata.get('gpsdestlongitude')), 6)

        return geo_dict

    def prepare_commonsfilename(self, commonsfilename)->str:
        commonsfilename = commonsfilename.strip()
        if commonsfilename.startswith("File:") == False:
            commonsfilename = "File:" + commonsfilename
        commonsfilename = commonsfilename.replace("_", " ")
        return commonsfilename

    def write_iptc(self, path, caption, keywords):
        # path can be both filename or directory
        assert os.path.exists(path)

        '''
        To prevent duplication when adding new items, specific items can be deleted then added back again in the same command. For example, the following command adds the keywords "one" and "two", ensuring that they are not duplicated if they already existed in the keywords of an image:

exiftool -keywords-=one -keywords+=one -keywords-=two -keywords+=two DIR
        '''

        # workaround for write utf-8 keywords: write them to file
        argfiletext = ''
        if isinstance(keywords, list) and len(keywords) > 0:
            for keyword in keywords:
                argfiletext += '-keywords-='+keyword+''+" \n"+'-keywords+='+keyword+' '+"\n"

        argfile = tempfile.NamedTemporaryFile()
        argfilename = 't.txt'
        with open(argfilename, 'w') as f:
            f.write(argfiletext)

        cmd = [self.exiftool_path, '-preserve', '-overwrite_original', '-charset iptc=UTF8', '-charset', 'utf8', '-codedcharacterset=utf8',
               '-@', argfilename, path]
        print(' '.join(cmd))
        response = subprocess.run(cmd, capture_output=True)

        if isinstance(caption, str):
            cmd = [self.exiftool_path, '-preserve', '-overwrite_original',
                   '-Caption-Abstract='+caption+'', path]
            response = subprocess.run(cmd, capture_output=True)

    def print_structured_data(self, commonsfilename):
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        commonsfilename = self.prepare_commonsfilename(commonsfilename)
        commons_site = pywikibot.Site("commons", "commons")

        # File to test and work with

        page = pywikibot.FilePage(commons_site, commonsfilename)

        # Retrieve Wikibase data
        item = page.data_item()
        item.get()

        for prop in item.claims:
            for statement in item.claims[prop]:
                if isinstance(statement.target, pywikibot.page._wikibase.ItemPage):
                    print(prop, statement.target.id,
                          statement.target.labels.get("en"))
                else:
                    print(prop, statement.target)

    def append_image_descripts_claim(self, commonsfilename, entity_list, dry_run):
        warnings.warn('moved to model_wiki', DeprecationWarning, stacklevel=2)
        assert isinstance(entity_list, list)
        assert len(entity_list) > 0
        if dry_run:
            print('simulate add entities')
            self.pp.pprint(entity_list)
            return
        commonsfilename = self.prepare_commonsfilename(commonsfilename)

        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        page = pywikibot.Page(site, title=commonsfilename, ns=6)
        media_identifier = "M{}".format(page.pageid)

        # fetch exist structured data

        request = site.simple_request(
            action="wbgetentities", ids=media_identifier)
        raw = request.submit()
        existing_data = None
        if raw.get("entities").get(media_identifier).get("pageid"):
            existing_data = raw.get("entities").get(media_identifier)

        try:
            depicts = existing_data.get("statements").get("P180")
        except:
            depicts = None
        for entity in entity_list:
            if depicts is not None:
                # Q80151 (hat)
                if any(
                    statement["mainsnak"]["datavalue"]["value"]["id"] == entity
                    for statement in depicts
                ):
                    print(
                        "There already exists a statement claiming that this media depicts a "
                        + entity
                        + " continue to next entity"
                    )
                    continue

            statement_json = {
                "claims": [
                    {
                        "mainsnak": {
                            "snaktype": "value",
                            "property": "P180",
                            "datavalue": {
                                "type": "wikibase-entityid",
                                "value": {
                                    "numeric-id": entity.replace("Q", ""),
                                    "id": entity,
                                },
                            },
                        },
                        "type": "statement",
                        "rank": "normal",
                    }
                ]
            }

            csrf_token = site.tokens["csrf"]
            payload = {
                "action": "wbeditentity",
                "format": "json",
                "id": media_identifier,
                "data": json.dumps(statement_json, separators=(",", ":")),
                "token": csrf_token,
                "summary": "adding depicts statement",
                # in case you're using a bot account (which you should)
                "bot": False,
            }

            request = site.simple_request(**payload)
            try:
                request.submit()
            except pywikibot.data.api.APIError as e:
                print("Got an error from the API, the following request were made:")
                print(request)
                print("Error: {}".format(e))

    def commons2stock_dev(self, url, city_wdid, images_dir='stocks', dry_run=False, date=None):

        site = pywikibot.Site('commons', 'commons')
        file_page = pywikibot.FilePage(site, url.replace(
            'https://commons.wikimedia.org/wiki/', ''))

        data_item = file_page.data_item()
        data_item.get()

        wd_ids = list()

        for prop in data_item.claims:
            if prop != 'P180':
                continue
            for statement in data_item.claims[prop]:
                if isinstance(statement.target, pywikibot.page._wikibase.ItemPage):
                    print(prop, statement.target.id)
                    wd_ids.append(statement.target.id)

        if not os.path.isdir(images_dir):
            os.makedirs(images_dir)
        filename = os.path.join(images_dir, url.replace(
            'https://commons.wikimedia.org/wiki/File:', ''))
        if not os.path.exists(filename):
            self.logger.debug('download: '+filename)
            file_page.download(filename)

        caption, keywords = self.get_shutterstock_desc(
            filename=filename,
            wikidata_list=wd_ids,
            city=city_wdid,
            date=date,
        )

        if dry_run:
            print()
            print(filename)
            print(caption)
            print(', '.join(keywords))
            return

        self.write_iptc(filename, caption, keywords)
        # processed_files.append(filename)
    
    def deprecated_replace_duplicated(self,filepath:str):
        """
        for folder with commons_dublicated subfolder:
        upload files using new filenames and new descriptions, taken from .desccription files
        append to old files description template {{duplicate}} with link to new file on commons
        """
        from model_wiki import Model_wiki
        modelwiki = Model_wiki()
        filepath = os.path.join(filepath,'commons_duplicates')
        if not os.path.exists(filepath):
            print(filepath.ljust(50)+' '+' not exist')
            quit()
        assert os.path.exists(filepath)
        files, uploaded_folder_path = self.input2filelist(filepath,mode='replace_duplicates')
        files_filtered = list()
        total_files = 0
        for filename in files:
            print(filename)
            if 'commons_uploaded' in filename:
                continue
            if filename.endswith('.description'):
                files_filtered.append(filename)
                total_files = total_files + 1
        files = files_filtered
        del files_filtered
        import pickle
        for filename in files:
            if 'commons_uploaded' in filename:
                continue
            file = open(filename, 'rb')
            photo_duplicate_desc = pickle.load(file)
            file.close()
            #photo_duplicate_desc={'old_filename':old_filename,'desc':texts["text"],'new_name':texts["name"],'wikidata_list':wikidata_list,'need_create_categories':texts['need_create_categories']}
            upload_messages = self.upload_file(
                    photo_duplicate_desc['filename'], photo_duplicate_desc['new_name'], photo_duplicate_desc['desc'], ignore_warning=True
                )
            print(upload_messages)

            self.logger.info('append claims')
            claims_append_result = modelwiki.append_image_descripts_claim(
                photo_duplicate_desc['new_name'], photo_duplicate_desc['wikidata_list'])
            
            # CREATE CATEGORY PAGES
            if len(photo_duplicate_desc['need_create_categories'])>0:
                for ctd in photo_duplicate_desc['need_create_categories']:
                    if not modelwiki.is_category_exists(ctd['name']):
                        self.logger.info()
                    modelwiki.create_category(ctd['name'], ctd['content'])
                    

            # move uploaded file to subfolder
            
            self.move_file_to_uploaded_dir(filename, uploaded_folder_path)
            self.move_file_to_uploaded_dir(photo_duplicate_desc['filename'], uploaded_folder_path)

            #add duplicate template to previous uploaded photo
            print('add to old file:')
            print(photo_duplicate_desc['old_filename'])

            modelwiki.file_add_duplicate_template('File:'+photo_duplicate_desc['old_filename'],new_filename=photo_duplicate_desc['new_name'])


    def process_and_upload_files(self, filepath, desc_dict):
        from model_wiki import Model_wiki
        modelwiki = Model_wiki()
        if not os.path.exists(filepath):
            print(filepath.ljust(50)+' '+' not exist')
            quit()
        assert os.path.exists(filepath)
        assert desc_dict['mode'] in ['object', 'vehicle', 'building']

        assert 'country' in desc_dict

        if not 'secondary_objects' in desc_dict:
            # for simple call next function
            desc_dict['secondary_objects'] = list()
        if not 'dry_run' in desc_dict:
            desc_dict['dry_run'] = False  # for simple call next function
        if not 'later' in desc_dict:
            desc_dict['later'] = False  # for simple call next function
        if not 'verify' in desc_dict:
            desc_dict['verify'] = False  # for simple call next function
        if 'country' in desc_dict:
            desc_dict['country'] = desc_dict['country'].title()
        else:
            desc_dict['country'] = None

        files, uploaded_folder_path = self.input2filelist(filepath)

        if len(files) == 0:
            quit()

        dry_run = desc_dict['dry_run']
        if desc_dict['later'] == True:
            dry_run = True

        uploaded_paths = list()
        files_filtered = list()
        # count for progressbar
        total_files = 0
        pbar = tqdm(files)
        for filename in pbar:
            pbar.set_description(filename)
            if 'commons_uploaded' in filename:
                continue
            
            if self.check_exif_valid(filename) and self.check_extension_valid(filename):
                files_filtered.append(filename)
                total_files = total_files + 1
            else:
                self.logger.info(filename+' invalid')
    
        progressbar_on = False
        if total_files > 1 and 'progress' in desc_dict:
            progressbar_on = True
            pbar = tqdm(total=total_files)

        files = files_filtered
        del files_filtered
        for filename in files:
            if 'commons_uploaded' in filename:
                continue
            if not(os.path.isfile(filename)):
                # this section goes when upload mp4: mp4 converted to webp, upload failed, then run second time, mp4 moved, webp uploaded, ciycle continued   
                continue
            

            secondary_wikidata_ids = modelwiki.input2list_wikidata(
                desc_dict['secondary_objects'])

            # get wikidata from filepath

            if secondary_wikidata_ids == [] and 'Q' in filename:
                secondary_wikidata_ids = self.get_wikidatalist_from_string(
                    filename)

            if desc_dict['mode'] == 'object':
                if desc_dict['wikidata'] == 'FROMFILENAME':
                    if not self.get_wikidatalist_from_string(filename):
                        self.logger.error(filename.ljust(
                            80)+': no wikidata in filename, skip upload')
                        continue  # continue to next file
                    wikidata = self.get_wikidatalist_from_string(filename)[
                        0]
                    del secondary_wikidata_ids[0]
                else:
                    if os.path.isfile(desc_dict['wikidata']):
                        wikidata=desc_dict['wikidata']
                    else:
                        wikidata = modelwiki.wikidata_input2id(
                        desc_dict['wikidata'])

                texts = self.make_image_texts_simple(
                    filename=filename,
                    wikidata=wikidata,
                    country=desc_dict['country'],
                    rail=desc_dict.get('rail'),
                    secondary_wikidata_ids=secondary_wikidata_ids,
                    quick=desc_dict['later']
                )
                if texts is None: continue
                wikidata=texts['wikidata'] #if wikidata taken from gpkg file
                wikidata_list = list()
                wikidata_list.append(wikidata)
                wikidata_list += secondary_wikidata_ids

                
                wikidata_list_upperlevel = list()
                for wd in wikidata_list:
                    entity_list = modelwiki.wikidata2instanceof_list(wd)
                    if entity_list is not None:
                        wikidata_list_upperlevel += entity_list
                wikidata_list += wikidata_list_upperlevel
                del wikidata_list_upperlevel
                del entity_list


            elif desc_dict['mode'] == 'vehicle':
                desc_dict['model'] = modelwiki.wikidata_input2id(
                    desc_dict.get('model', None))
                # transfer street user input deeper, it can be vector file name
                desc_dict['street'] = desc_dict.get('street', None)

                desc_dict['city'] = modelwiki.wikidata_input2id(
                    desc_dict.get('city', None))
                desc_dict['line'] = modelwiki.wikidata_input2id(
                    desc_dict.get('line', None))


                texts = self.make_image_texts_vehicle(
                    filename=filename,
                    vehicle=desc_dict['vehicle'],
                    model=desc_dict.get('model', None),
                    street=desc_dict.get('street', None),
                    number=desc_dict.get('number', None),
                    digital_number=desc_dict.get('digital_number', None),
                    system=desc_dict.get('system', None),
                    route=desc_dict.get('route', None),
                    country=desc_dict.get('country', None),
                    line=desc_dict.get('line', None),
                    operator=desc_dict.get('operator', None),
                    operator_vehicle_category=desc_dict.get('operator_vehicle_category', None),
                    facing=desc_dict.get('facing', None),
                    colors=desc_dict.get('colors', None),
                    secondary_wikidata_ids=secondary_wikidata_ids
                )
                if texts is None:
                    # invalid metadata for this file, continue to next file
                    continue
                wikidata_list = list()
                wikidata_list += texts['structured_data_on_commons']
                wikidata_list += secondary_wikidata_ids
                standalone_captions_dict = {
                    'new_filename': texts['name'], 'ru': texts['captions']['ru'], 'en': texts['captions']['en']}

                '''
                    'new_filename':commons_filename,'ru':objectname_long_ru,'en':objectname_long_en
                '''
            # HACK
            # UPLOAD WEBP instead of TIFF if tiff is big
            # if exists file with webp extension:
            filename_webp = filename.replace('.tif', '.webp')
            src_filesize_mb = os.path.getsize(filename) / (1024 * 1024)
            if filename.endswith('.tif') and src_filesize_mb > self.tiff2webp_min_size_mb :
                print('file is big, convert to webp to bypass upload errors')
                self.convert_to_webp(filename)

            if filename.endswith('.tif') and os.path.isfile(filename_webp):
                print(
                    'found tif and webp file with same name. upload webp with fileinfo from tif')
                if not dry_run:
                    self.move_file_to_uploaded_dir(
                        filename, uploaded_folder_path)
                filename = filename_webp
                texts["name"] = texts["name"].replace('.tif', '.webp')
                
            if filename.lower().endswith(('.mp4','.mov')):
                video_converted_filename=self.convert_to_webm(filename)
            if filename.lower().endswith(('.mp4','.mov')) and os.path.isfile(video_converted_filename):
                print(
                    'found mp4 and webm file with same name. upload webm with fileinfo from mp4')
                if not dry_run:
                    self.move_file_to_uploaded_dir(
                        filename, uploaded_folder_path)
                filename = video_converted_filename
                texts["name"] = texts["name"].replace('.mp4', '.webm').replace('.MP4', '.webm').replace('.MOV', '.webm').replace('.mov', '.webm')         
                

            print(texts["name"])
            print(texts["text"])
            

            #remove duplicates
            wikidata_list = list(dict.fromkeys(wikidata_list))
            
            #print wikidata entitines for append
            templist=list()
            for wdid in wikidata_list:
                wd = modelwiki.get_wikidata_simplified(wdid)
                templist.append('【'+wd['labels'].get('en','no en label')+'】')
            print('-'.join(templist))
            del templist

                
            if not dry_run:
                if '_replace' in filename:
                    #ignore_warning=True
                    
                    if '_reupload' in filename:
                        self.logger.info('replace file..')
                        modelwiki.replace_file_commons( modelwiki.pagename_from_id(self.get_replace_id_from_string(filename)),filename)

                    self.logger.info('You should manualy replace texts. Open https://commons.wikimedia.org/entity/M'+self.get_replace_id_from_string(filename))
                    print('Texts for manual update')
                    
                    txt = "{{Rename|"+texts["name"]+"|2|More detailed object name, taken from wikidata}}"
                    print(txt)
                    print(texts["text"])
                    input("Press Enter to continue...")
                    # CREATE CATEGORY PAGES
                    if len(texts['need_create_categories'])>0:
                        for ctd in texts['need_create_categories']:
                            if not modelwiki.is_category_exists(ctd['name']):
                                self.logger.info('creating category '+ctd['name'])
                            modelwiki.create_category(ctd['name'], ctd['content'])
                            

                    # move uploaded file to subfolder
                    if not dry_run:
                        self.move_file_to_uploaded_dir(
                            filename, uploaded_folder_path)

                    if progressbar_on:
                        pbar.update(1)
                
                    
                    continue
                else:
                    ignore_warning = False
                upload_messages = self.upload_file(
                    filename, texts["name"], 
                    texts["text"], 
                    verify_description=desc_dict['verify'],
                    ignore_warning = ignore_warning
                )

                print(upload_messages)



            self.logger.info('append claims')
            claims_append_result = modelwiki.append_image_descripts_claim(
                texts["name"], wikidata_list, dry_run)
            if not dry_run:
                modelwiki.create_category_taken_on_day(
                    texts['country'].title(), texts['dt_obj'].strftime("%Y-%m-%d"))
            else:
                print('will append '+' '.join(wikidata_list))

            uploaded_paths.append(
                'https://commons.wikimedia.org/wiki/File:'+texts["name"].replace(' ', '_'))

            if claims_append_result is None:
                # UPLOAD FAILED
                if 'Uploaded file is a duplicate of' in upload_messages:
                    old_filename = self.get_old_filename_from_overwrite_error(upload_messages)
                    uploaded_folder_path_dublicate = uploaded_folder_path.replace(
                        'commons_uploaded', 'commons_duplicates')
                    self.move_file_to_uploaded_dir(
                        filename, uploaded_folder_path_dublicate)
                    
                    # write description to text file for panoramio-replace process
                    import pickle
                    photo_duplicate_desc={'old_filename':old_filename,
                                          'desc':texts["text"],
                                          'filename':os.path.join(uploaded_folder_path_dublicate,os.path.basename(filename)),
                                          'new_name':texts["name"],
                                          'wikidata_list':wikidata_list,
                                          'need_create_categories':texts['need_create_categories']}
                    photo_duplicate_desc_filename = os.path.join(uploaded_folder_path_dublicate,os.path.splitext(os.path.basename(filename))[0]+'.description')
                    file = open(photo_duplicate_desc_filename, 'wb')
                    pickle.dump(photo_duplicate_desc, file)
                    file.close()
                # Continue to next file
                #continue
            else:
                self.logger.info('check if replace old photo')
                # REPLACE old panoramio photo. New photo uploaded, server not triggered at dublicate:
                if '_replace' in filename:
                    
                    old_file_pageid = self.get_replace_id_from_string(filename)
                    old_file_pagename = modelwiki.pagename_from_id(old_file_pageid)
                    self.logger.info('add template for replace '+old_file_pagename)
                    modelwiki.file_add_duplicate_template(pagename=old_file_pagename,new_filename=texts["name"])


            # CREATE CATEGORY PAGES
            if len(texts['need_create_categories'])>0:
                for ctd in texts['need_create_categories']:
                    if not modelwiki.is_category_exists(ctd['name']):
                        self.logger.info('creating category '+ctd['name'])
                    modelwiki.create_category(ctd['name'], ctd['content'])
                    

            # move uploaded file to subfolder
            if not dry_run:
                self.move_file_to_uploaded_dir(
                    filename, uploaded_folder_path)

            if progressbar_on:
                pbar.update(1)

        if progressbar_on:
            pbar.close()
        if not dry_run:
            self.logger.info('uploaded: ')
        else:
            self.logger.info('emulating upload. URL will be: ')

        self.logger.info("\n".join(uploaded_paths))

       
                
                
                
                
    def get_old_filename_from_overwrite_error(self,upload_message:str)->str:
        '''
        from 'We got the following warning(s): duplicate: Uploaded file is a duplicate of ['Krasnogorsk-2013_-_panoramio_(320).jpg'].'
        return Krasnogorsk-2013_-_panoramio_(320).jpg
        
        '''

        import re
        test_str = upload_message
        regex = r"\['(.*?)'\]"
        matches = re.finditer(regex, test_str, re.MULTILINE)

        for matchNum, match in enumerate(matches, start=1):
            
            #print ("Match {matchNum} was found at {start}-{end}: {match}".format(matchNum = matchNum, start = match.start(), end = match.end(), match = match.group()))
            
            for groupNum in range(0, len(match.groups())):
                groupNum = groupNum + 1
                
                #print ("Group {groupNum} found at {start}-{end}: {group}".format(groupNum = groupNum, start = match.start(groupNum), end = match.end(groupNum), group = match.group(groupNum)))

                return match.group(groupNum)
        

    def convert_to_webm(self,filename)->str:
        # convert video to webm vp9. files not overwriten
        filename_dst = filename.replace('.mp4', '.webm').replace('.MP4', '.webm').replace('.MOV', '.webm').replace('.mov', '.webm')  
        if os.path.isfile(filename_dst): return filename_dst

        cmd = ['ffmpeg', '-i',filename, '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '30', '-pass', '1', '-row-mt', '1', '-an', '-f', 'webm', '-y', '/dev/null']
        print(' '.join(cmd))
        response = subprocess.run(cmd)

        cmd = ['ffmpeg', '-i', filename, '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '30', '-pass', '2', '-row-mt', '1', '-c:a', 'libopus',   filename_dst]
        print(' '.join(cmd))
        response = subprocess.run(cmd)
        return filename_dst
        
    def move_file_to_uploaded_dir(self, filename, uploaded_folder_path):
        # move uploaded file to subfolder
        if not os.path.exists(uploaded_folder_path):
            os.makedirs(uploaded_folder_path)
        shutil.move(filename, os.path.join(
            uploaded_folder_path, os.path.basename(filename)))
