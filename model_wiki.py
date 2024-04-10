import pywikibot
import json

from exif import Image
import locale

from datetime import datetime
from dateutil import parser
import os
import logging
import pprint
import subprocess
from transliterate import translit
from pywikibot.specialbots import UploadRobot
from pywikibot import pagegenerators
from pywikibot import exceptions

import urllib
import wikitextparser as wtp
from simple_term_menu import TerminalMenu
import pickle
import re
import traceback
from tqdm import tqdm


from fileprocessor import Fileprocessor


class Model_wiki:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    pp = pprint.PrettyPrinter(indent=4)

    wiki_content_cache = dict()
    cache_category_object_in_location = dict()
    cache_settlement_for_object = dict()
    wikidata_cache = dict()
    wikidata_cache_filename = 'temp_wikidata_cache.dat'
    optional_langs = ('de', 'fr', 'it', 'es', 'pt', 'uk', 'be', 'ja')

    def __init__(self):
        if not os.path.isfile('user-config.py'):
            raise Exception('''Now you should enter Wikimedia user data in config. Call \n cp user-config.example.py user-config.py
        \n open user-config.py in text editor, input username,  and run this script next time''')

        self.wikidata_cache = self.wikidata_cache_load(
            wikidata_cache_filename=self.wikidata_cache_filename)

    def reset_cache(self):
        os.unlink(self.wikidata_cache_filename)
        self.wikidata_cache = self.wikidata_cache_load(
            wikidata_cache_filename=self.wikidata_cache_filename)

    def replace_file_commons(self, pagename, filepath):
        assert pagename
        # Login to your account
        site = pywikibot.Site('commons', 'commons')
        site.login()
        site.get_tokens("csrf")  # preload csrf token

        # Replace the file
        file_page = pywikibot.FilePage(site, pagename)

        file_page.upload(source=filepath, comment='Replacing file',ignore_warnings=True, watch=True)

        return

    def wikidata_cache_load(self, wikidata_cache_filename):
        if os.path.isfile(wikidata_cache_filename) == False:
            cache = {'entities_simplified': {},  
                     'commonscat_by_2_wikidata': {}, 
                     'cities_ids':{},
                     'commonscat_exists_set': set()}
            return cache
        else:
            file = open(wikidata_cache_filename, 'rb')

            # dump information to that file
            cache = pickle.load(file)

            # close the file
            file.close()
            return cache

    def wikidata_cache_save(self, cache, wikidata_cache_filename) -> bool:
        file = open(wikidata_cache_filename, 'wb')

        # dump information to that file
        pickle.dump(cache, file)

        # close the file
        file.close()

    def wikipedia_get_page_content(self, page) -> str:

        # check cache
        import sys
        pagename = page.title()
        if pagename in self.wiki_content_cache:
            return self.wiki_content_cache[pagename]

        pagecode = page.text
        self.wiki_content_cache[pagename] = pagecode
        assert sys.getsizeof(pagecode) > 25

        return pagecode

    def is_change_need(self, pagecode, operation) -> bool:
        operations = ('taken on', 'taken on location')
        assert operation in operations

        if operation == 'taken on':
            if '{{Taken on'.upper() in pagecode.upper():
                return False
            else:
                return True

        return False

    def page_name_canonical(self, pagecode) -> str:
        # [[commons:File:Podolsk, Moscow Oblast, Russia - panoramio (152).jpg]]
        # File:Podolsk, Moscow Oblast, Russia - panoramio (152).jpg

        pagecode = str(pagecode)
        pagecode = pagecode.replace('https://commons.wikimedia.org/wiki/', '')
        pagecode = pagecode.replace('[[commons:', '').replace(']]', '')
        return pagecode

    def url_add_template_taken_on(self, pagename, location, dry_run=True,verbose=False,interactive=False):
        assert pagename
        location = location.title()
        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        pagename = self.page_name_canonical(pagename)
        if not pagename.startswith('File:'): pagename='File:'+pagename
        page = pywikibot.Page(site, title=pagename)


        self.page_template_taken_on(page, location, dry_run, verbose,interactive)

    def category_add_template_wikidata_infobox(self,category:str):
        if not category.startswith('Category:'):
            category = 'Category:'+category
        assert category
        texts = dict()
        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        category = self.page_name_canonical(category)
        page = pywikibot.Page(site, title=category)

        texts[0] = page.text
        if 'wikidata infobox' in texts[0].lower():
            return True
		
        message = '{{Wikidata Infobox}}'
        texts[1]=message+"\n"+page.text
        page.text = texts[1]
        page.save('add {{Wikidata Infobox}} template')


    def category_add_template_taken_on(self, categoryname, location, dry_run=True, interactive=False, levels=0, skip_location=''):
        assert categoryname
        total_files = 0
        def page_generators(categoryname):
            site = pywikibot.Site("commons", "commons")
            site.login()
            site.get_tokens("csrf")  # preload csrf token
            category = pywikibot.Category(site, categoryname)
            
            regex = '(?i)date.*=.*2\d\d\d-\d\d-\d\d.*\}\}'
            regex = '(?i)Information[\S\s]*date[\S\s]*=[\S\s]*2\d\d\d-\d\d-\d\d.*\}\}'
            gen1 = pagegenerators.CategorizedPageGenerator(
                category, recurse=levels, start=None, total=None, content=True, namespaces=None)

            gen2 = pagegenerators.RegexBodyFilterPageGenerator(gen1, regex)
            return gen2
        
        rejected_usernames=['test_string_for_skip_artem_svetlov_bot','Юрий Д.К.']
        pagegenerator=page_generators(categoryname)
        pagenames=list()
        for page in pagegenerator:
        

            
            print(page,end='')
            badpage=False
            if not str(page)[2:-2].lower().endswith(('jpg','jpeg','tif','webm','webp')): 
                print(' < skip this format',end='')
                badpage=True
            if any(ele in page.text for ele in rejected_usernames): 
                print(' < skip this user ',end='')
                badpage=True
            if skip_location != '' and '|location='+skip_location in page.text:
                print(' < skip this location ',end='')
                badpage=True
            
            if badpage==False: pagenames.append(page.title())
            print()
            
            total_files = total_files+1
        print('filtered pages list:')    
        print("\n".join(pagenames))

        logging.getLogger().setLevel(logging.WARNING)

        
        location = location.title()
        pbar = tqdm(total=total_files)
        
        pagegenerator=page_generators(categoryname)
        for page in pagegenerator:
            if not str(page)[2:-2].lower().endswith(('jpg','jpeg','tif','webm','webp')): continue
            if any(ele in page.text for ele in rejected_usernames): continue
            
            self.page_template_taken_on(
                page, location, dry_run, interactive, verbose=False, message=f'Set taken on location={location} for files in category {categoryname}')
            pbar.update(1)
        pbar.close()

    def location_string_parse(self, text) -> tuple:
        if text is None:
            return None, None
        text = text.strip()
        if text is None or text == "":
            return None, None
        struct = re.split(" |,|\t|\|", text)
        if len(struct) < 2:
            return None, None
        return float(struct[0]), float(struct[-1])


    def create_wikidata_item(self,wd_object):
        '''
        created with bing ai 
        https://www.bing.com/search?iscopilotedu=1&sendquery=1&q=%D0%A7%D1%82%D0%BE+%D1%82%D0%B0%D0%BA%D0%BE%D0%B5+%D0%BD%D0%BE%D0%B2%D1%8B%D0%B9+Bing%3F&showconv=1&filters=wholepagesharingscenario%3A%22Conversation%22&shareId=4d855391-009e-4938-81b4-8591617df8db&shtc=0&shsc=Codex_ConversationMode&form=EX0050&shid=b116c20e-9d13-494d-a4cc-8f8b3a8a6260&shtp=GetUrl&shtk=0J7Qt9C90LDQutC%2B0LzRjNGC0LXRgdGMINGBINGN0YLQuNC8INC%2B0YLQstC10YLQvtC8IEJpbmc%3D&shdk=0JLQvtGCINC%2B0YLQstC10YIsINC%2F0L7Qu9GD0YfQtdC90L3Ri9C5INGBINC%2F0L7QvNC%2B0YnRjNGOINC90L7QstC%2B0LPQviBCaW5nLCDQs9C70L7QsdCw0LvRjNC90L7QuSDRgdC40YHRgtC10LzRiyDQvtGC0LLQtdGC0L7QsiDQvdCwINCx0LDQt9C1INC40YHQutGD0YHRgdGC0LLQtdC90L3QvtCz0L4g0LjQvdGC0LXQu9C70LXQutGC0LAuINCp0LXQu9C60L3QuNGC0LUg0LTQu9GPINC%2F0YDQvtGB0LzQvtGC0YDQsCDQvtGC0LLQtdGC0LAg0YbQtdC70LjQutC%2B0Lwg0Lgg0L%2FQvtC%2F0YDQvtCx0YPQudGC0LUg0Y3RgtGDINGE0YPQvdC60YbQuNGOINGB0LDQvNC%2B0YHRgtC%2B0Y%2FRgtC10LvRjNC90L4u&shhk=KUktXhHaQFr142oHDgOzFPKk2Snr3G22dzXkpH3KtHg%3D&shth=OBFB.107AF8B2FB79BD01FFDCABA4D756224A



        
        '''
        # create a site object for wikidata
        site = pywikibot.Site("wikidata", "wikidata")
        # create a new item
        new_item = pywikibot.ItemPage(site)

        # set the labels, descriptions and aliases from the wd_object
        try:
            new_item.editLabels(labels=wd_object["labels"], summary="Setting labels")
            new_item.editDescriptions(descriptions=wd_object["descriptions"], summary="Setting descriptions")
            new_item.editAliases(aliases=wd_object["aliases"], summary="Setting aliases")
        except:
            self.logger.warning('prorably this building already created in wikidata. merge not implement yet')
            pass
        self.logger.info('created https://www.wikidata.org/wiki/'+str(new_item.getID()))
        # iterate over the claims in the wd_object
        for prop, value in wd_object["claims"].items():
            # create a claim object for the property
            claim = pywikibot.Claim(site, prop)
            # check the type of the value
            if isinstance(value, str) and self.is_wikidata_id(value):
                # it is a wikidata item id
                # get the item object for the value
                target = pywikibot.ItemPage(site, value)
            elif isinstance(value, dict) and self.is_wikidata_id(value.get('value',None)):
                # it is a wikidata item id
                # get the item object for the value
                target = pywikibot.ItemPage(site, value.get('value'))                
            elif isinstance(value, dict):
                # if the value is a dict, it is a special value type
                # check the type of the value
                if value["value"].get("latitude"):
                    # if the value has latitude, it is a coordinate type
                    # create a coordinate object for the value
                    target = pywikibot.Coordinate(
                        lat=value["value"]["latitude"],
                        lon=value["value"]["longitude"],
                        precision=value["value"]["precision"],
                        site=site,
                        #globe=value["value"]["globe"],
                    )
                elif value["value"].get("time"):
                    # if the value has time, it is a time type
                    # create a time object for the value
                    target = pywikibot.WbTime(
                        year=int(value["value"]["time"]["year"]),
                        #month=value["value"]["time"]["month"],
                        #day=value["value"]["time"]["day"],
                        #hour=value["value"]["time"]["hour"],
                        #minute=value["value"]["time"]["minute"],
                        #second=value["value"]["time"]["second"],
                        precision=value["value"]["precision"],
                        #calendarmodel=value["value"]["calendarmodel"],
                    )
                elif value["value"].get("amount"):
                    # if the value has amount, it is a quantity type
                    # create a quantity object for the value
                    target = pywikibot.WbQuantity(
                        amount=value["value"]["amount"],
                        unit=value["value"]["unit"],
                        error=value["value"].get("error"),
                        site=site
                    )
                else:
                    # otherwise, the value is not supported
                    # raise an exception
                    raise ValueError(f"Unsupported value type: {value}")
            else:
                # otherwise, the value is not supported
                # raise an exception
                raise ValueError(f"Unsupported value type: {value}")
            # set the target of the claim to the value object
            claim.setTarget(target)
            # check if the value has qualifiers
            if isinstance(value, dict) and value.get("qualifiers"):
                # iterate over the qualifiers
                for qual_prop, qual_value in value["qualifiers"].items():
                    # create a qualifier object for the property
                    qualifier = pywikibot.Claim(site, qual_prop)
                    # check the type of the qualifier value
                    if isinstance(qual_value, str) and self.is_wikidata_id(qual_value):
                        # if the qualifier value is a wikidata item id
                        # get the item object for the qualifier value
                        qual_target = pywikibot.ItemPage(site, qual_value)
                    elif isinstance(qual_value, str):
                        # qualifier value is string
                        qual_target = qual_value
                    elif isinstance(qual_value, dict):
                        # if the qualifier value is a dict, it is a special value type
                        # check the type of the qualifier value
                        if qual_value["value"].get("latitude"):
                            # if the qualifier value has latitude, it is a coordinate type
                            # create a coordinate object for the qualifier value
                            qual_target = pywikibot.Coordinate(
                                lat=qual_value["value"]["latitude"],
                                lon=qual_value["value"]["longitude"],
                                precision=qual_value["value"]["precision"],
                                site=site,
                                #globe=qual_value["value"]["globe"],
                            )
                        elif qual_value["value"].get("time"):
                            # if the qualifier value has time, it is a time type
                            # create a time object for the qualifier value
                            qual_target = pywikibot.WbTime(
                                year=int(qual_value["value"]["time"]["year"]),
                                #month=qual_value["value"]["time"]["month"],
                                #day=qual_value["value"]["time"]["day"],
                                #hour=qual_value["value"]["time"]["hour"],
                                #minute=qual_value["value"]["time"]["minute"],
                                #second=qual_value["value"]["time"]["second"],
                                precision=qual_value["value"]["precision"],
                                #calendarmodel=qual_value["value"]["calendarmodel"],
                            )
                        elif qual_value["value"].get("amount"):
                            # if the qualifier value has amount, it is a quantity type
                            # create a quantity object for the qualifier value
                            qual_target = pywikibot.WbQuantity(
                                amount=qual_value["value"]["amount"],
                                unit=qual_value["value"]["unit"],
                                error=qual_value["value"].get("error"),
                                site=site
                            )
                        else:
                            # otherwise, the qualifier value is not supported
                            # raise an exception
                            raise ValueError(f"Unsupported qualifier value type: {qual_value}")
                    else:
                        # otherwise, the qualifier value is not supported
                        # raise an exception
                        raise ValueError(f"Unsupported qualifier value type: {qual_value}")
                    # set the target of the qualifier to the qualifier value object
                    qualifier.setTarget(qual_target)
                    # add the qualifier to the claim
                    claim.addQualifier(qualifier, summary="Adding qualifier")
            # check if the value has references
            if isinstance(value, dict) and value.get("references"):
                # iterate over the references
                for reference in value["references"]:
                    # create a list of source claims for the reference
                    source_claims = []
                    # iterate over the reference properties and values
                    for ref_prop, ref_value in reference.items():
                        # create a source claim object for the property
                        source_claim = pywikibot.Claim(site, ref_prop)
                        # check the type of the reference value
                        if isinstance(ref_value, str):
                            # if the reference value is a string, it is a wikidata item id or a url
                            # check if the reference value starts with http
                            if ref_value.startswith("http"):
                                # if the reference value is a url, create a url object for the reference value
                                ref_target = ref_value
                                #source_claim.is_reference=True ???
                            else:
                                # if the reference value is a wikidata item id, get the item object for the reference value
                                ref_target = pywikibot.ItemPage(site, ref_value)
                        elif isinstance(ref_value, dict):
                            # if the reference value is a dict, it is a special value type
                            # check the type of the reference value
                            if ref_value["value"].get("latitude"):
                                # if the reference value has latitude, it is a coordinate type
                                # create a coordinate object for the reference value
                                ref_target = pywikibot.Coordinate(
                                    lat=ref_value["value"]["latitude"],
                                    lon=ref_value["value"]["longitude"],
                                    precision=ref_value["value"]["precision"],
                                    globe=ref_value["value"]["globe"],
                                )
                            elif ref_value["value"].get("time"):
                                # if the reference value has time, it is a time type
                                # create a time object for the reference value
                                ref_target = pywikibot.WbTime(
                                    year=int(ref_value["value"]["time"]["year"]),
                                    #month=ref_value["value"]["time"]["month"],
                                    #day=ref_value["value"]["time"]["day"],
                                    #hour=ref_value["value"]["time"]["hour"],
                                    #minute=ref_value["value"]["time"]["minute"],
                                    #second=ref_value["value"]["time"]["second"],
                                    precision=ref_value["value"]["precision"],
                                    #calendarmodel=ref_value["value"]["calendarmodel"],
                                )
                            elif ref_value["value"].get("amount"):
                                # if the reference value has amount, it is a quantity type
                                # create a quantity object for the reference value
                                ref_target = pywikibot.WbQuantity(
                                    amount=ref_value["value"]["amount"],
                                    unit=ref_value["value"]["unit"],
                                    error=ref_value["value"].get("error"),
                                    site=site
                                )
                            else:
                                # otherwise, the reference value is not supported
                                # raise an exception
                                raise ValueError(f"Unsupported reference value type: {ref_value}")
                        else:
                            # otherwise, the reference value is not supported
                            # raise an exception
                            raise ValueError(f"Unsupported reference value type: {ref_value}")
                        # set the target of the source claim to the reference value object
                        source_claim.setTarget(ref_target)
                        # append the source claim to the source claims list
                        source_claims.append(source_claim)
                    # add the source claims as a reference to the claim
                    claim.addSources(source_claims, summary="Adding reference")
            # add the claim to the new item
            new_item.addClaim(claim, summary="Adding claim")
        # return the new item id
        return new_item.getID()
        
    def claim_dict2pywikibot_claim(self,repo, claim):
        """
        return new pywikibot claim object for add to wikidata using pywikibot from dict 
        """

    def create_street_wikidata(self,city,name_en,coords,name_ru=None,named_after=None, street_type='Q79007',country=None,dry_mode=False)->str:
        wikidata_template = """
    {
      "type": "item",
      "labels": {
        "en": ""
      },
      "descriptions": {
        "en": ""
      },
      "aliases": {},
      "claims": {
        "P31": "Q79007",
        "P625":{ 
            "value":{
          "latitude": 55.666,
          "longitude": 37.666,
          "precision": 0.0001,
          "globe": "http://www.wikidata.org/entity/Q2"
            }
        }
      }
    }
    """
        


        city_wd = self.get_wikidata_simplified(city)
        street_type_wd = self.get_wikidata_simplified(street_type)
        wd_object = json.loads(wikidata_template)
        wd_object["labels"]["en"] = name_en
        wd_object["descriptions"]["en"] = street_type_wd['labels']['en'] + ' in ' + city_wd['labels']['en']
        if name_ru is not None:
            wd_object["labels"]["ru"] = name_ru
        wd_object["descriptions"]["ru"] = street_type_wd['labels']['ru'] + ' в ' + city_wd['labels']['ru']

        # COORDINATES
        if 'LINESTRING' in coords.upper():
            #line with 3 points: write coordinates for start, middle, end of street
            from model_geo import Model_Geo as Model_geo_ask
            coords_list =  Model_geo_ask.extract_wktlinestring_to_points(coords)
            assert len(coords_list) in (2,3)
            
            
            
        else: 
            lat=None
            lon=None
            lat, lon = self.location_string_parse(coords)

            assert lat is not None
            assert lon is not None
            
            
            wd_object["claims"]["P625"]["value"]["latitude"] = round(
                float(lat), 5
            )  # coords
            wd_object["claims"]["P625"]["value"]["longitude"] = round(
                float(lon), 5
            )  # coords

        # State
        country_claim=self.get_best_claim(city,'P17')
        wd_object["claims"]["P17"] = country_claim
        # located in adm
        wd_object["claims"]["P131"] = city_wd['id']
        if named_after is not None: wd_object["claims"]["P138"] = named_after

        if dry_mode:
            print(json.dumps(wd_object, indent=1))
            self.logger.info("dry mode, no creating wikidata entity")
            return

        new_item_id = self.create_wikidata_item(wd_object)
        self.logger.info(f'street object created: https://www.wikidata.org/wiki/{new_item_id} ')
        return new_item_id

    def create_wikidata_building(self, data, dry_mode=False):
        assert "street_wikidata" in data

        # get street data from wikidata
        assert data["street_wikidata"] is not None

        street_dict_wd = self.get_wikidata_simplified(data["street_wikidata"])
        city_wd = self.get_wikidata_simplified(data["city"])
        data["street_name_ru"] = street_dict_wd["labels"]["ru"]
        data["street_name_en"] = street_dict_wd["labels"]["en"]

        wikidata_template = """
    {
      "type": "item",
      "labels": {
        "ru": ""
      },
      "descriptions": {
        "ru": ""
      },
      "aliases": {},
      "claims": {
        "P31": "Q41176",
        "P17": "Q159",
        "P625":{ 
            "value":{
          "latitude": 55.666,
          "longitude": 37.666,
          "precision": 0.0001,
          "globe": "http://www.wikidata.org/entity/Q2"
            }
        }
      }
    }
    """
        
        # sample
       

        data["lat"], data["lon"] = self.location_string_parse(
            data["latlonstr"])

        assert data["lat"] is not None
        assert data["lon"] is not None
        assert data["street_name_ru"] is not None
        assert data["street_name_en"] is not None
        assert data["housenumber"] is not None
        assert data["street_wikidata"] is not None
        wd_object = json.loads(wikidata_template)
        wd_object["labels"]["ru"] = data["street_name_ru"] + \
            " " + data["housenumber"]
        wd_object["labels"]["en"] = self.address_international(
        city=city_wd['labels']['en'],
        street=data["street_name_en"], 
        housenumber=data["housenumber"]).strip()

        wd_object["descriptions"]["ru"] = "Здание в " + city_wd['labels']['ru']
        wd_object["descriptions"]["en"] = "Building in " + city_wd['labels']['en']
        wd_object["aliases"] = {"ru": list()}
        wd_object["aliases"]["ru"].append(
            city_wd['labels']['ru'] + ' ' + data["street_name_ru"] +
            " дом " + data["housenumber"]
        )
        wd_object["claims"]["P625"]["value"]["latitude"] = round(
            float(data["lat"]), 5
        )  # coords
        wd_object["claims"]["P625"]["value"]["longitude"] = round(
            float(data["lon"]), 5
        )  # coords
        if data.get("coord_source", None) is not None and data["coord_source"].lower() == "yandex maps":
            wd_object["claims"]["P625"]["references"] = list()
            wd_object["claims"]["P625"]["references"].append(dict())
            wd_object["claims"]["P625"]["references"][0]["P248"] = "Q4537980"
        if data.get("coord_source", None) is not None and data["coord_source"].lower() == "osm":
            wd_object["claims"]["P625"]["references"] = list()
            wd_object["claims"]["P625"]["references"].append(dict())
            wd_object["claims"]["P625"]["references"][0]["P248"] = "Q936"
        if data.get("coord_source", None) is not None and data["coord_source"].lower() == "reforma":
            wd_object["claims"]["P625"]["references"] = list()
            wd_object["claims"]["P625"]["references"].append(dict())
            wd_object["claims"]["P625"]["references"][0]["P248"] = "Q117323686"
        wd_object["claims"]["P669"] = {
            "value": data["street_wikidata"],
            "qualifiers": {"P670": data["housenumber"]},
        }
        
        if "district_wikidata"  in data:
            wd_object["claims"]["P131"]={
            "value": data["district_wikidata"]
            }        
        if "project"  in data:
            wd_object["claims"]["P144"]={
            "value": data["project"]
            }

        if "year" in data:
            wd_object["claims"]["P1619"] = {
                "value": {"time": {"year":int(str(data["year"])[0:4])},"precision":9}}
            if "year_source" or "year_url" in data:
                wd_object["claims"]["P1619"]["references"] = list()
                wd_object["claims"]["P1619"]["references"].append(dict())
                if data.get("year_source") == "2gis":
                    wd_object["claims"]["P1619"]["references"][0]["P248"] = "Q112119515"
                if data.get("year_source") == "wikimapia":
                    wd_object["claims"]["P1619"]["references"][0]["P248"] = "Q187491"
                if 'https://2gis.ru' in data.get('year_url', ''):
                    wd_object["claims"]["P1619"]["references"][0]["P248"] = "Q112119515"
                if 'reformagkh.ru' in data.get('year_url', ''):
                    wd_object["claims"]["P1619"]["references"][0]["P248"] = "Q117323686"

                if "year_url" in data:
                    wd_object["claims"]["P1619"]["references"][0]["P854"] = data[
                        "year_url"
                    ]

        if "levels" in data:
            wd_object["claims"]["P1101"] = {
                "value": {"amount": int(data["levels"]), "unit": None,"error":None}
            }
            if "levels_source" or "levels_url" in data:
                wd_object["claims"]["P1101"]["references"] = list()
                wd_object["claims"]["P1101"]["references"].append(dict())
                if data.get("levels_source") == "2gis":
                    wd_object["claims"]["P1101"]["references"][0]["P248"] = "Q112119515"
                if data.get("levels_source") == "wikimapia":
                    wd_object["claims"]["P1101"]["references"][0]["P248"] = "Q187491"
                if 'https://2gis.ru' in data.get('levels_url', ''):
                    wd_object["claims"]["P1101"]["references"][0]["P248"] = "Q112119515"
                if 'reformagkh.ru' in data.get('levels_url', ''):
                    wd_object["claims"]["P1101"]["references"][0]["P248"] = "Q117323686"

            if "levels_url" in data:
                wd_object["claims"]["P1101"]["references"][0]["P854"] = data["levels_url"]

        if 'building' in data and data['building'] is not None:
            wd_object["claims"]["P31"] = data['building']
        if 'architect' in data and data['architect'] is not None:
            wd_object["claims"]["P84"] = data['architect']
        if 'architecture' in data and data['architecture'] is not None:
            if data['architecture']=='Q34636': data['architecture']='Q1295040' # art noveau --> art noveau architecture
            wd_object["claims"]["P149"] = data['architecture']




        if dry_mode:
            print(json.dumps(wd_object, indent=1))
            self.logger.info("dry mode, no creating wikidata entity")
            return

        new_item_id = self.create_wikidata_item(wd_object)
        print("created https://www.wikidata.org/wiki/" + new_item_id)
        if data.get('category') is not None:
            self.wikidata_add_commons_category(new_item_id, data.get('category'))
            self.category_add_template_wikidata_infobox(data.get('category'))
        
        return new_item_id

    def get_territorial_entity(self, wd_record) -> dict:
        if 'P131' not in wd_record['claims']:
            return None
        object_wd = self.get_wikidata_simplified(
            wd_record['claims']['P131'][0]['value'])
        return object_wd


    def validate_street_in_building_record(self, data):
        assert data["street_wikidata"] is not None
        wd_street = self.get_wikidata_simplified(data["street_wikidata"])
        result = None
        
        if 'commons' not in wd_street:
            self.logger.debug(
                "street "
                + wikidata_street_url
                + " must have wikimedia commons category"
            )
            return False
        if result is None:
            result = True
        return True

        
    def get_wikidata_simplified(self, entity_id) -> dict:
        assert entity_id is not None
        # get all claims of this wikidata objects
        if entity_id in self.wikidata_cache['entities_simplified']:
            return self.wikidata_cache['entities_simplified'][entity_id]

        site = pywikibot.Site("wikidata", "wikidata")
        entity = pywikibot.ItemPage(site, entity_id)
        entity.get()

        object_record = {'labels': {}}

        labels_pywikibot = entity.labels.toJSON()
        for lang in labels_pywikibot:
            object_record['labels'][lang] = labels_pywikibot[lang]['value']

        object_record['id'] = entity.getID()
        claims = dict()
        wb_claims = entity.toJSON()['claims']

        for prop_id in wb_claims:
            
            claims[prop_id] = list()
            for claim in wb_claims[prop_id]:

                claim_s=dict()
                claim_s['rank']=claim.get('rank',None)
                if prop_id=='P1101':                
                    pass
                if 'datatype' not in claim['mainsnak']:
                    pass
                    # this is 'somevalue' claim, skip, because it not simply
                elif claim['mainsnak']['datatype'] == 'wikibase-item':
                    claim_s['value'] = 'Q'+str(claim['mainsnak']['datavalue']['value']['numeric-id'])
                elif claim['mainsnak']['datatype'] == 'time':
                    claim_s['value'] = claim['mainsnak']['datavalue']['value']['time'][8:]
                    claim_s['precision'] = claim['mainsnak']['datavalue']['value']['precision']
                elif claim['mainsnak']['datatype'] == 'external-id':
                    claim_s['value'] = str(claim['mainsnak']['datavalue']['value'])
                elif claim['mainsnak']['datatype'] == 'string':
                    claim_s['value'] = str(claim['mainsnak']['datavalue']['value'])
                elif claim['mainsnak']['datatype'] == 'quantity':
                    claim_s['value'] = str(claim['mainsnak']['datavalue']['value'])
                elif claim['mainsnak']['datatype'] == 'monolingualtext':
                    claim_s['value'] =  claim['mainsnak']['datavalue']['value']['text'] 
                    claim_s['language'] = str(claim['mainsnak']['datavalue']['value']['language'])
                if 'qualifiers' in claim:  claim_s['qualifiers'] = claim['qualifiers']
                claims[prop_id].append(claim_s)

        object_record['claims'] = claims

        wb_sitelinks = entity.toJSON().get('sitelinks', dict())
        commons_sitelink = ''
        if 'commonswiki' in wb_sitelinks:
            commons_sitelink = wb_sitelinks['commonswiki']['title']

        if "P373" in object_record['claims']:
            object_record['commons'] = object_record["claims"]["P373"][0]["value"]
        elif 'commonswiki' in wb_sitelinks:
            object_record['commons'] = wb_sitelinks['commonswiki']['title'].replace(
                'Category:', '')
        else:
            object_record['commons'] = None

        '''if "en" not in object_wd["labels"]:
            self.logger.error('object https://www.wikidata.org/wiki/' +
                              wikidata+' must have english label')
            return None
        '''

        self.wikidata_cache['entities_simplified'][entity_id] = object_record
        self.wikidata_cache_save(
            self.wikidata_cache, self.wikidata_cache_filename)
        return object_record

    def page_template_taken_on(self, page, location, dry_run=True, interactive=False, verbose=True,message='set Taken on location for manual set list of images'):
        assert page
        texts = dict()
        page_not_need_change = False
        texts[0] = page.text

        if '.svg'.upper() in page.full_url().upper():
            return False
        if '.png'.upper() in page.full_url().upper():
            return False
        if '.ogg'.upper() in page.full_url().upper():
            return False
        
        if '{{Information'.upper() not in texts[0].upper():
            self.logger.debug(
                'template Information not exists in '+page.title())
            return False
        if '|location='.upper()+location.upper() in texts[0].upper():
            self.logger.debug('|location='+location+' already in page')
            page_not_need_change = True
            texts[1] = texts[0]
        else:
            try:
                texts[1] = self._text_add_template_taken_on(texts[0])
            except:
                raise ValueError('invalid page text in ' + page.full_url())
        if 'Taken on'.upper() in texts[1].upper() or 'Taken in'.upper() in texts[1].upper() or 'According to Exif data'.upper(
        ) in texts[1].upper():
            print('wrong text in '+page.title())

        datestr = self.get_date_from_pagetext(texts[1])
        if datestr == False:
            return False
        if '/' in datestr:
            raise ValueError(
                'Slash symbols in date causes side-effects. Normalize date in '+page.full_url())
        if len(datestr) < len('yyyy-mm-dd'):
            return False
        if len(datestr) > len('yyyy-mm-dd'):
            return False        
        assert datestr, 'invalid date parce in '+page.full_url()

        location_value_has_already = self._text_get_template_taken_on_location(
            texts[1])

        if location_value_has_already is None:
            texts[2] = self._text_add_template_taken_on_location(
                texts[1], location)
        else:
            texts[2] = self._text_get_template_replace_on_location(
                texts[1], location)

        if texts[2] == False:
            return False
        if '|location='+location+'}}' not in texts[2]:
            return False
        # Remove category
        cat='Russia photographs taken on '+datestr
        texts[2]=texts[2].replace("[[Category:"+cat+"]]",'')
        texts[2]=texts[2].replace("[[Category:"+cat.replace(' ','_')+"]]",'')
        
        # Remove category
        cat=location+' photographs taken on '+datestr
        texts[2]=texts[2].replace("[[Category:"+cat+"]]",'')
        texts[2]=texts[2].replace("[[Category:"+cat.replace(' ','_')+"]]",'')



        date_obj = datetime.strptime(datestr, '%Y-%m-%d')
        date_obj.strftime('%B %Y')
        cat=date_obj.strftime('%B %Y')+' in '+location
        texts[2]=texts[2].replace("[[Category:"+cat+"]]",'')
        texts[2]=texts[2].replace("[[Category:"+cat.replace(' ','_')+"]]",'')

        cat=date_obj.strftime('%Y')+' in '+location
        texts[2]=texts[2].replace("[[Category:"+cat+"]]",'')
        texts[2]=texts[2].replace("[[Category:"+cat.replace(' ','_')+"]]",'')

        cat=date_obj.strftime('%Y')+' in Russia'
        texts[2]=texts[2].replace("[[Category:"+cat+"]]",'')
        texts[2]=texts[2].replace("[[Category:"+cat.replace(' ','_')+"]]",'')


        self.difftext(texts[0], texts[2])
        if texts[0]!=texts[2]:page_not_need_change = False

        if verbose:
            print('----------- proposed page content ----------- ' +
                  datestr + '--------')

            print(texts[2])
        if not dry_run and not interactive:
            page.text = texts[2]
            if page_not_need_change == False:
                page.save(message)
            self.create_category_taken_on_day(location, datestr)
        else:
            print('page not changing')

        if interactive:
            answer = input(" do change on  "+page.full_url() + "\n y / n   ? ")
            # Remove white spaces after the answers and convert the characters into lower cases.
            answer = answer.strip().lower()

            if answer in ["yes", "y", "1"]:
                page.text = texts[2]
                page.save(message+' with manual preview')
                self.create_category_taken_on_day(location, datestr)


    @staticmethod
    def is_wikidata_id(text) -> bool:
        # check if string is valid wikidata id
        if not isinstance(text,str): return False
        if text.startswith('Q') and text[1:].isnumeric():
            return True
        else:
            return False

    @staticmethod
    def search_wikidata_by_string(text, stop_on_error=True) -> str:
        warnings.warn('use wikidata_input2id',
                      DeprecationWarning, stacklevel=2)
        cmd = ['wb', 'search', '--json', text]

        response = subprocess.run(cmd, capture_output=True)
        object_wd = json.loads(response.stdout.decode())
        if stop_on_error:
            if not len(object_wd) > 0:
                raise ValueError('not found in wikidata: '+text)

        return object_wd[0]['id']

    def file_add_duplicate_template(self, pagename='',id='',new_filename=''):
        '''
        append {{Duplicate|new_filename|message}} to old commons file
        pagename formats: File:photoname.jpg  or concept URL https://commons.wikimedia.org/entity/M56911766
        '''
        assert new_filename != ''
        assert pagename != '' or id != ''
        if id != '': assert id.startswith('M')
        
        texts = dict()
        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        if pagename != '':
            page = pywikibot.Page(site, title=pagename)
        else:
            page = pywikibot.Page(site,id) 

        texts[0] = page.text
		
        message = '{{Duplicate|'+new_filename+'|Replace Panoramio import with original file from photographer (me) with better name and categories}}'
        texts[1]=message+"\n"+page.text
        page.text = texts[1]
        page.save('add {{duplicate}} template')

    def get_heritage_types(self, country='RU') -> list:
        template = '''
        SELECT ?item ?label ?_image WHERE {
  ?item wdt:P279 wd:Q8346700.
  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "ru" . 
    ?item rdfs:label ?label
  }
}

'''
        sparql = template
        site = pywikibot.Site("wikidata", "wikidata")
        repo = site.data_repository()

        generator = pagegenerators.PreloadingEntityGenerator(
            pagegenerators.WikidataSPARQLPageGenerator(sparql, site=repo))
        items_ids = list()
        for item in generator:
            items_ids.append(item.id)
        heritage_types = {"RU": items_ids}
        return heritage_types


    def get_settlements_wdids(self) -> list:

        if len(self.wikidata_cache['cities_ids'])>1:
            return self.wikidata_cache['cities_ids']
        '''
        return list of settlements types ids
        '''
        template = '''
        SELECT ?item ?label ?_image WHERE {
  ?item wdt:P279 wd:Q7930989.
  SERVICE wikibase:label {
    bd:serviceParam wikibase:language "en" . 
    ?item rdfs:label ?label
  }
}

'''
        sparql = template
        site = pywikibot.Site("wikidata", "wikidata")
        repo = site.data_repository()

        generator = pagegenerators.PreloadingEntityGenerator(
            pagegenerators.WikidataSPARQLPageGenerator(sparql, site=repo))
        items_ids = list()
        for item in generator:
            items_ids.append(item.id)

        self.wikidata_cache['cities_ids'] = items_ids
        self.wikidata_cache_save(
            self.wikidata_cache, self.wikidata_cache_filename)
        return items_ids


    def get_heritage_id(self, wdid) -> str:
        # if wikidata object "heritage designation" is one of "culture heritage in Russia" - return russian monument id
        # for https://www.wikidata.org/wiki/Q113683163 reads P1483, returns '6931214010' or None

        site = pywikibot.Site("wikidata", "wikidata")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        item = pywikibot.ItemPage(site, wdid)
        item.get()

        if 'P1435' not in item.claims:
            return None
        if 'P1483' not in item.claims:
            return None

        heritage_types = self.get_heritage_types('RU')
        claims = item.claims.get("P1435")
        for claim in claims:
            if claim.getTarget().id in heritage_types['RU']:
                heritage_claim = item.claims.get("P1483")[0]
                return heritage_claim.getTarget()

        return None

    def wikidata_input2id(self, inp) -> str:
        if inp is None:
            return None
        candidates = list()

        # detect user input string for wikidata
        # if user print a query - search wikidata
        # returns wikidata id

        inp = self.prepare_wikidata_url(inp)
        if inp.startswith('Q'):
            return self.normalize_wdid(inp)

        site = pywikibot.Site("wikidata", "wikidata")

        # Use the wbsearchentities action to get a list of possible matches
        # See https://www.mediawiki.org/wiki/Wikibase/API#wbsearchentities for details
        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "type": "item",
            "search": inp,
        }
        request = pywikibot.data.api.Request(site=site, **params)
        results = request.submit()

        # Print the results
        for result in results["search"]:
            # Get the entity ID, label, description and URL
            entity_id = result["id"]
            label = result["label"]
            description = result.get("description", "No description")
            url = result["url"]
            candidates.append(result['id']+' '+result['label'] +
                              ' '+result.get("description", "No description"))
        
     
        
        if len(candidates) == 1:
            selected_url = results["search"][0]['id']
            return selected_url
        else:
            try:
                terminal_menu = TerminalMenu(
                    candidates, title="Select wikidata entity for " + inp)
                menu_entry_index = terminal_menu.show()
            except:
                # special for run in temmux
                menu_entry_index = self.user_select(candidates)
            selected_url = results["search"][menu_entry_index]['id']
        print('For '+inp+' selected 【'+selected_url+' ' +
              results["search"][menu_entry_index]['description']+'】')

        return selected_url

    def user_select(self, candidates):
        i = 0
        for element in candidates:
            print(str(i).rjust(3)+': '+element)
            i = i+1
        print('Enter a number:')
        result = input()
        return int(result.strip())

    def prepare_wikidata_url(self, wikidata) -> str:
        # convert string https://www.wikidata.org/wiki/Q4412648 to Q4412648

        wikidata = str(wikidata).strip()
        wikidata = wikidata.replace('https://www.wikidata.org/wiki/', '')
        if wikidata[0].isdigit() and not wikidata.upper().startswith('Q'):
            wikidata = 'Q'+wikidata
        return wikidata

    def difftext(self, text1, text2):
        l = 0
        is_triggered = 0
        text1_dict = {i: text1.splitlines()[i] for i in range(len(text1.splitlines()))}
        text2_dict = {i: text2.splitlines()[i] for i in range(len(text2.splitlines()))}
        
        for l in range(0, len(text1.splitlines())):
            if text1_dict.get(l,' - - - - - void string - - - ') != text2_dict.get(l,' - - - - - void string - - - '):
                is_triggered += 1
                if is_triggered == 1:
                    print()
                print(text1_dict.get(l,' - - - - - void string - - - '))
                print(text2_dict.get(l,' - - - - - void string - - - '))
                print('^^^^^text changed^^^^^')

    def _text_get_template_replace_on_location(self, test_str, location):
        import re

        regex = r"^.*(?:Information|photograph)[\s\S]*?Date\s*?=.*location=(?P<datecontent>[\s\S]*?)[\|\}}\n].*$"

        matches = re.finditer(regex, test_str, re.UNICODE |
                              re.MULTILINE | re.IGNORECASE)

        for matchNum, match in enumerate(matches, start=1):

            for groupNum in range(0, len(match.groups())):
                groupNum = groupNum + 1

                groupstart = match.start(groupNum)
                groupend = match.end(groupNum)
                content = match.group(groupNum)

        text = test_str[0:groupstart] + location+test_str[groupend:]
        return text

    def _text_get_template_taken_on_location(self, test_str):
        # return content of "location" if exists

        import re

        regex = r"^.*(?:Information|photograph)[\s\S]*?Date\s*?=.*location=(?P<datecontent>[\s\S]*?)[\|\}}\n].*$"

        matches = re.search(regex, test_str, re.IGNORECASE |
                            re.UNICODE | re.MULTILINE)

        if matches:

            for groupNum in range(0, len(matches.groups())):
                groupNum = groupNum + 1

                return (matches.group(groupNum))

    def is_taken_on_in_text(self, test_str):
        import re

        regex = r"^.*(?:Information|photograph)[\s\S]*?Date\s*?=.*?(taken on|According to Exif data)\s*?[\|\n].*$"

        matches = re.search(regex, test_str, re.IGNORECASE |
                            re.UNICODE | re.MULTILINE)

        if matches:

            for groupNum in range(0, len(matches.groups())):
                groupNum = groupNum + 1

                if matches.group(groupNum) is not None:
                    return True
        return False

    def _text_add_template_taken_on(self, test_str):
        assert test_str

        if self._text_get_template_taken_on_location(test_str) is not None:
            return test_str
        if self.is_taken_on_in_text(test_str):
            return test_str
        # test_str name comes from onine regex editor
        import re

        regex = r"^.*(?:Information|photograph)[\s\S]*?Date\s*?=(?P<datecontent>[\s\S]*?)[\|\n].*$"

        matches = re.finditer(regex, test_str, re.UNICODE |
                              re.MULTILINE | re.IGNORECASE)

        for matchNum, match in enumerate(matches, start=1):

            for groupNum in range(0, len(match.groups())):
                groupNum = groupNum + 1

                groupstart = match.start(groupNum)
                groupend = match.end(groupNum)
                content = match.group(groupNum)

        text = test_str[0:groupstart] + \
            ' {{Taken on|'+content.strip()+"}}"+test_str[groupend:]
        return text

    def input2list_wikidata(self, inp):

        if inp is None or inp == False:
            return list()
        if isinstance(inp, str):
            inp = ([inp])
        secondary_wikidata_ids = list()
        for inp_wikidata in inp:
            wdid = self.wikidata_input2id(inp_wikidata)
            secondary_wikidata_ids.append(wdid)
        return secondary_wikidata_ids

    def _text_add_template_taken_on_location(self, test_str, location):

        if '|location'.upper() in test_str.upper():
            return False
        # test_str name comes from onine regex editor
        import re

        regex = r"^.*(?:Information|photograph)[\s\S]*Date\s*=\s*{{(?:Taken on|According to Exif data)\s*\|[\s\S]*?(?P<taken_on_end>)}}.*$"

        matches = re.finditer(regex, test_str, re.MULTILINE | re.IGNORECASE)

        for matchNum, match in enumerate(matches, start=1):

            for groupNum in range(0, len(match.groups())):
                groupNum = groupNum + 1

                groupstart = match.start(groupNum)
                groupend = match.end(groupNum)
                content = match.group(groupNum)

        text = test_str[0:groupstart] + '|location=' + \
            location+""+test_str[groupend:]
        return text

    def get_date_from_pagetext(self, test_str) -> str:
        content = ''
        # test_str name comes from onine regex editor
        import re

        regex = r"^.*?(?:Information|photograph)[\s\S]*?Date\s*=\s*{{(?:Taken on|According to Exif data)\s*\|(?P<datecontent>[\s\S]*?)(?:}}|\|).*$"

        matches = re.finditer(regex, test_str, re.MULTILINE | re.IGNORECASE)

        for matchNum, match in enumerate(matches, start=1):

            for groupNum in range(0, len(match.groups())):
                groupNum = groupNum + 1

                groupstart = match.start(groupNum)
                groupend = match.end(groupNum)
                content = match.group(groupNum)

        if content == '':
            print("not found date in \n"+test_str)
            return False
        text = content.strip()
        text = text[:10]
        try:
            parser.parse(text)
        except:
            print('invalid date: '+text)
            return False
        return text
    
    def create_street_category(self,street_wikidata:str, city_wikidata:str=None)-> str:
        if street_wikidata is None:
            return None
        assert street_wikidata.startswith("Q")
        street_wd = self.get_wikidata_simplified(street_wikidata)
        if 'en' not in street_wd['labels']:
            self.logger.error('object https://www.wikidata.org/wiki/' +
                              street_wikidata+' must have english label')
            return None

        if city_wikidata is not None:      
            assert city_wikidata.startswith("Q")
            city_wd = self.get_wikidata_simplified(city_wikidata)
            if 'en' not in city_wd['labels']:
                self.logger.error('object https://www.wikidata.org/wiki/' +
                                city_wikidata+' must have english label')
                return None
        else:
            city_wikidata = street_wd['claims']['P131'][0]['value']
            city_wd = self.get_wikidata_simplified(city_wikidata)

                
        # MAKE CATEGORY NAME
        streetname = street_wd['labels']['en']
        cityname = city_wd['labels']['en']
        catname = f'{streetname}, {cityname}'
        uppercat = self.get_category_object_in_location('Q79007',city_wikidata,verbose=True)
        content = """{{Wikidata infobox}}
        {{GeoGroup}}
        [[Category:%uppercat%]]
        """
        content = content.replace('%uppercat%',uppercat)
        content = content.replace('%cityname%',cityname)
        if not self.is_category_exists(catname):
            self.create_category(catname,content)
            self.wikidata_add_commons_category(street_wikidata,catname)
        else:
            print('category already exists')

        return catname
        
    def address_international(self,city:str,street:str, housenumber:str)->str:
        """
        from [Riga, Gertrudes street, 25] return "Gertrudes street 25, Riga" 
        House number translitireted from RU to LAT 
        """
        if city.strip() == '':
            template = '{street} {housenumber}'
        else:
            template='{street} {housenumber}, {city}'
        
        result = template.format(city=city,
                                                       street=street,
                                                       housenumber=translit(housenumber,"ru",reversed=True,
                ))
        return result 
                
    def create_building_category(self, wikidata:str, city_wikidata:str, dry_mode=False ) -> str:
        """
        Create wikimedia commons category for wikidata building entity

        Return: category name
        """
        if wikidata is None and dry_mode:
            print("commons category will be created here...")
            return


        assert wikidata.startswith("Q")
        building_dict_wd=self.get_wikidata_simplified(wikidata)
        city_dict_wd=self.get_wikidata_simplified(city_wikidata)
       

        assert "P669" in building_dict_wd["claims"], (
            "https://www.wikidata.org/wiki/"
            + wikidata
            + " must have P669 street name and housenumber"
        )
        # retrive category name for street
        #in saint petersburg one building trasitionaly may has 2 or 4 street addresses in located in street crossing
        #cycle for all streets
        
        category_streets=list()

        for street_counter in range(0,len(building_dict_wd['claims']['P669'])):
            street_dict_wd = self.get_wikidata_simplified(building_dict_wd['claims']['P669'][street_counter]['value'])
            housenumber = building_dict_wd["claims"]["P669"][street_counter]['qualifiers']['P670'][0]["datavalue"]["value"]
            assert street_dict_wd['commons'] is not None
            
            category_street = street_dict_wd['commons']     
            category_street +='|'+housenumber.zfill(2)
            category_streets.append(category_street)
            del category_street
            del housenumber
            del street_dict_wd
        #get one prefered street for category name

        street_dict_wd = self.get_wikidata_simplified(building_dict_wd['claims']['P669'][0]['value'])
        housenumber = building_dict_wd["claims"]["P669"][0]['qualifiers']['P670'][0]["datavalue"]["value"]
        assert street_dict_wd['commons'] is not None
        category_street = street_dict_wd['commons']     
        category_street +='|'+housenumber.zfill(2)
               
        category_name = self.address_international(city=city_dict_wd['labels']['en'],
                                       street=street_dict_wd['labels']['en'],
                                       housenumber=housenumber)
        del category_street

        
        year = ""
        decade = ""
        year_field = None
        if "P1619" in building_dict_wd["claims"]:
            year_field = "P1619"
        elif "P580" in building_dict_wd["claims"]:
            year_field = "P580"
            year_field = "P1619"
        elif "P571" in building_dict_wd["claims"]:
            year_field = "P571"
        elif "P729" in building_dict_wd["claims"]:
            year_field = "P729"
        if year_field is not None:
            try:
                if building_dict_wd["claims"][year_field][0]["precision"] >= 9:
                    year = building_dict_wd["claims"][year_field][0]["value"][0:4]
                if building_dict_wd["claims"][year_field][0]["precision"] == 8:
                    decade = (
                        building_dict_wd["claims"][year_field][0]["value"][0:3]
                        + "0"
                    )
            except:
                pass
            # no year in building
        assert isinstance(year, str)
        assert year == "" or len(year) == 4, "invalid year:" + str(year)
        assert decade == "" or len(decade) == 4, "invalid decade:" + str(decade)
        levels = 0
        try:
            levels = building_dict_wd["claims"]["P1101"][0]["value"]["amount"]
        except:
            pass
            # no levels in building
        assert isinstance(levels, int)
        assert levels == 0 or levels > 0, "invalid levels:" + str(levels)

        code = """
{{Object location}}
{{Wikidata infobox}}
{{Building address|Country=RU|City=%city%|Street name=%street%|House number=%housenumber%}}

"""
        # CULTURAL HERITAGE RUSSIA
        prop='P1483'
        if prop in building_dict_wd["claims"]:
            wlm_ru_code = self.get_best_claim(wikidata,prop)
            wlm_district_wdid = self.get_best_claim(wikidata,'P131')
            wlm_district_wd=self.get_wikidata_simplified(wlm_district_wdid)
            wlm_district_category=wlm_district_wd['commons']
            code += "{{Cultural Heritage Russia|id="+wlm_ru_code+"|category="+wlm_district_category+"}}" + "\n"
            
        if year != "":
            code += "[[Category:Built in %city% in %year%]]" + "\n"

        if decade != "":
            code += "[[Category:%decade%s architecture in %city%]]" + "\n"

        if levels > 0:
            code += "[[Category:%levelstr%-story buildings in %city%]]" + "\n"

        building_function='Buildings'
        for instance in building_dict_wd["claims"]["P31"]:
            #if instance['value'] in ('Q1081138')
            try:
                cat=self.get_category_object_in_location(instance['value'],street_dict_wd['id'],verbose=True)
                assert cat is not None 
                code += f"[[Category:{cat}]]" + "\n"
            except:
                self.logger.info('no category found for '+self.get_wikidata_simplified(instance['value'])['labels']['en'])

        code = code.replace("%city%", city_dict_wd['labels']['en'])
        #code = code.replace("%city_loc%", city_ru)
        code = code.replace("%street%", street_dict_wd["labels"]["en"])
        code = code.replace("%year%", year)
        code = code.replace("%housenumber%", housenumber)
        code = code.replace("%decade%", decade)
        
        for category_street in category_streets:
            code += "[[Category:%cat%]]".replace('%cat%',category_street) + "\n"
        
        
        if levels > 0 and levels < 21:
            code = code.replace("%levelstr%", str(num2words(levels).capitalize()))
        elif levels > 20:
            code = code.replace("%levelstr%", str(levels))




        # architector
        prop='P84'
        if prop in building_dict_wd["claims"]:
            architector_value = self.get_best_claim(wikidata,prop)
            category = self.get_category_object_in_location(architector_value,street_dict_wd['id'])
            if category is not None:
                code += "\n[[Category:"+category+"]]"
            else:
                category = self.get_wikidata_simplified(architector_value)["commons"]
                code += "\n[[Category:"+category+"]]"
            del category
            del architector_value
            
        # architectural style
        prop='P149'
        if prop in building_dict_wd["claims"]:
            style_value = self.get_best_claim(wikidata,prop)
            category = self.get_category_object_in_location(style_value,street_dict_wd['id'])
            if category is not None:
                code += "\n[[Category:"+category+"]]"
            else:
                category = self.get_wikidata_simplified(style_value)["commons"]
                code += "\n[[Category:"+category+"]]"
            del category
            del style_value
            
        # project
        prop='P144'
        if prop in building_dict_wd["claims"]:
            project_value = self.get_best_claim(wikidata,prop)
            category = self.get_category_object_in_location(project_value,street_dict_wd['id'],verbose=True)
            if category is not None:
                code += "\n[[Category:"+category+"]]"
            else:
                category = self.get_wikidata_simplified(project_value)["commons"]
                code += "\n[[Category:"+category+"]]"
            del category
            del project_value
        
        # part of
        prop='P361'
        if prop in building_dict_wd["claims"]:
            partof_value = self.get_best_claim(wikidata,prop)
            category = self.get_wikidata_simplified(partof_value)["commons"]
            code += "\n[[Category:"+category+"]]"
            del category
            del partof_value         
        
        if dry_mode:
            print()
            print(category_name)
            print(code)
            self.logger.info("dry mode, no creating wikidata entity")
            return category_name
        commonscat_create_result = self.create_category(category_name, code)
        self.wikidata_add_commons_category(wikidata, category_name)
        category_name_building = category_name

        if year != "":
            city = city_dict_wd['labels']['en']
            category_name='Built in %city% in %year%'
            category_name = category_name.replace("%year%", year)
            category_name = category_name.replace("%city%", city)
            country_wdid = self.get_best_claim(city_dict_wd['id'],'P17')
            country_wd = self.get_wikidata_simplified(country_wdid)
            country = country_wd['labels']['en']
            code = """[[Category:Built in %country% in %year%| %city%]]
[[Category:Buildings in %city% by year of completion]]"""
            code =  code.replace("%year%", year)
            code =  code.replace("%city%", city)
            code =  code.replace("%country%", country)

            print(category_name)
            print(code)
            commonscat_create_result = self.create_category(category_name, code)


            category_name=f'Buildings in {city} by year of completion'
            code = """
{{metacat|year of completion}}
[[Category:Buildings in %city%| Year]]
[[Category:%city% by year|  ]]
[[Category:Buildings in %country% by year of completion by city|%city%]]
"""
            code =  code.replace("%year%", year)
            code =  code.replace("%city%", city)
            code =  code.replace("%country%", country)

            print(category_name)
            print(code)
            commonscat_create_result = self.create_category(category_name, code)
            

        return category_name_building
    
    def create_number_on_vehicles_category(self,vehicle:str,number:str):
        """
        Create commons category for vehicle number:
        Number 7854 on trolleybuses
        Number 5007 on trams

        """

        number=str(number)

        if vehicle=='bus':
            name = f'Number {number} on buses'
            content = '{{Numbercategory-buses|'+number+'}}'
            self.create_category(name, content)

            name = f'Number {number} on vehicles'
            content = '{{Numbercategory-vehicle|'+number+'|vehicle|Number '+number+' on objects|Vehicle}}'
            self.create_category(name, content)

            name = f'Number {number} on objects'
            content = '{{number on object|n='+number+'}}'
            self.create_category(name, content)
        
        if vehicle=='trolleybus':
            name = f'Number {number} on trolleybuses'
            content = '{{Numbercategory-trolleybuses|'+number+'}}'
            self.create_category(name, content)
            self.create_number_on_vehicles_category('bus',number)
        
        if vehicle=='tram':
            name = f'Trams with fleet number {number}'
            content = '{{tram fleet number|'+number+'|image=}}'
            self.create_category(name, content)
            
            name = f'Items numbered {number}'
            content = '{{number cat|nt=nom|n='+number+'}}'
            self.create_category(name, content)

                        
            name = f'Number {number} on trams'
            content = '{{numbercategoryTram|'+number+'}}'
            self.create_category(name, content)



    def create_vehicle_in_city_category(self,vehicle:str, number:str,city_name:str,model_name:str)->str:
        """
        create category for vehicle in city like "Moscow tram 1220"

        Returns: category name
        """
        city_name = city_name.capitalize()

        if vehicle == 'trolleybus':
            name = f'{city_name} trolleybus {number}'
            content = """{{GeoGroup}}
[[Category:%model_name% in %city_name%|%number%]]
[[Category:Trolleybuses in %city_name% by registration number]]
[[Category:Number %number% on trolleybuses]]


{{DEFAULTSORT:%number% }}
"""
            content = content.replace('%number%',number)
            content = content.replace('%model_name%',model_name)
            content = content.replace('%city_name%',city_name)

            self.create_category(name, content)
            self.create_number_on_vehicles_category('trolleybus',number)
        elif vehicle == 'tram':
            name = f'{city_name} tram {number}'
            content = """{{GeoGroup}}
[[Category:%model_name% in %city_name%|%number%]]
[[Category:Trams in %city_name% by fleet number]]
[[Category:Trams with fleet number %number% ]]


{{DEFAULTSORT:%number% }}
"""
            content = content.replace('%number%',number)
            content = content.replace('%model_name%',model_name)
            content = content.replace('%city_name%',city_name)

            self.create_category(name, content)
            self.create_number_on_vehicles_category('tram',number)
        else:
            self.logger.error(vehicle +' not implemented')
        return name
    def wikidata_add_commons_category(self,item_id:str, category_name:str):
        """
        Set a sitelink to a commons category in a wikidata item.

        Parameters:
        item_id (str): the ID of the wikidata item, e.g. 'Q42'
        category_name (str): the name of the commons category, e.g. 'Category:Albert Einstein'

        Returns:
        None
        """
        if not category_name.startswith('Category:'):
            category_name = 'Category:'+category_name

        # Create a site object for wikidata
        site = pywikibot.Site('wikidata', 'wikidata')
        # Create an item object from the item ID
        item = pywikibot.ItemPage(site, item_id)
        # Create a site object for commons
        commons = pywikibot.Site('commons', 'commons')
        # Create a page object from the category name
        category = pywikibot.Page(commons, category_name)
        # Check if the category exists and is a category page
        if not category.exists():
            self.logger.error('category not exists:'+category_name)
            return None
        if category.exists() and category.is_categorypage():
            # Set the sitelink to the category
            item.setSitelink(category, summary='Set sitelink to commons category')
            # Delete old commons category link claim P373 if exist
            item.get() # load the item data
            claims = item.claims # get the claims dictionary
            if "P373" in claims: # check if the item has the property
                claim = claims["P373"][0] # get the first (and only) claim for that property
                item.removeClaims([claim]) # remove the claim
                print("Claim P373 removed")
        else:
            # Print an error message
            print('Invalid category name')
        self.reset_cache()

    def create_category_taken_on_day(self, location, yyyymmdd):
        location = location.title()
        if len(yyyymmdd) != 10:
            return False

        categoryname = '{location}_photographs_taken_on_{yyyymmdd}'.format(
            location=location, yyyymmdd=yyyymmdd)

        pagename = 'Category:'+categoryname

        if location == 'Moscow':
            content = '{{Moscow photographs taken on navbox}}'
        else:
            content = '{{'+location+' photographs taken on navbox|' + \
                yyyymmdd[0:4]+'|'+yyyymmdd[5:7]+'|'+yyyymmdd[8:10]+'}}'
        # self.create_page(pagename, content, 'create category')
        self.create_category(pagename, content)

        if location in ('Moscow', 'Moscow Oblast', 'Saint Petersburg','Tatarstan','Nizhny Novgorod Oblast','Leningrad Oblast'):
            self.create_category_taken_on_day('Russia', yyyymmdd)

    def create_category(self, pagename: str, content: str):
        """
        Create wikimedia commons category

        pagename:   with or without category
        content:    text content
        """
        if not pagename.startswith('Category:'):
            pagename = 'Category:'+pagename
        if not self.is_category_exists(pagename):
            self.create_page(pagename, content, 'create category')
        else:
            self.logger.info('page already exists '+pagename)
    
    def wikidata2instanceof_list(self,wdid)->list:
        """
        from wikidata id return list of instance of wikidata ids
        """ 
        claims_list=list()
        wikidata = self.get_wikidata_simplified(wdid)
        for instance in wikidata["claims"].get("P31",list()):
            claims_list.append(instance['value'])
            
        return claims_list
    
    
    def is_category_exists(self, categoryname):
        if not categoryname.startswith('Category:'):
            categoryname = 'Category:'+categoryname
        # check in cache
        if categoryname in self.wikidata_cache['commonscat_exists_set']:
            return True

        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        page = pywikibot.Page(site, title=categoryname)

        if page.exists():
            self.wikidata_cache['commonscat_exists_set'].add(categoryname)
            self.wikidata_cache_save(
                self.wikidata_cache, self.wikidata_cache_filename)

        return page.exists()

    def create_page(self, title, content, savemessage):
        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        page = pywikibot.Page(site, title=title)
        page.text = content
        page.save(savemessage)

        return True

    def search_files_geo(self, lat, lon):
        site = pywikibot.Site("commons", "commons")
        pages = pagegenerators.SearchPageGenerator('Svetlov Artem filetype:bitmap nearcoord:2km,{lat},{lon}'.format(
            lat=lat, lon=lon), total=8, namespaces=None, site=site)

        return pages

    def get_building_record_wikidata(self, wikidata, stop_on_error=False) -> dict:
        building_wd = self.get_wikidata_simplified(wikidata)

        # get street of object
        if "P669" not in building_wd["claims"]:
            if stop_on_error:
                raise ValueError(
                    "object https://www.wikidata.org/wiki/"
                    + wikidata
                    + "should have street"
                )
            else:
                return None

        street_wd = self.get_wikidata_simplified(
            building_wd["claims"]["P669"][0]["value"])

        if 'qualifiers' not in building_wd["claims"]["P669"][0]:
            self.logger.error( "object https://www.wikidata.org/wiki/"
                    + wikidata
                    + "#P669 has [P669 Located on street]. If it has qualifier [P670 house number], this page name will improved. Upload without address text now")
            return None
        try:
            building_record = {
                "building": "yes",
                "addr:street:ru": street_wd["labels"]["ru"],
                "addr:street:en": street_wd["labels"]["en"],
                "addr:housenumber:local": building_wd["claims"]["P669"][0]["qualifiers"][
                    "P670"
                ][0]['datavalue']["value"],
                "addr:housenumber:en": building_wd["claims"]["P669"][0]["qualifiers"]["P670"][0]['datavalue']["value"],
            }
            building_record["addr:housenumber:en"] = translit(building_record["addr:housenumber:en"],'ru',reversed=True)
            building_record['commons'] = building_wd["commons"]
        except:
            return None

        return building_record

    def get_best_claim(self, wdid:str, prop:str) -> str:
        assert prop.startswith('P')
        entity=self.get_wikidata_simplified(wdid)
        claims=entity['claims'].get(prop)
        try:
            for claim in claims:
                if claim['rank']=='preferred':
                    return claim['value']
            for claim in claims:
                return claim['value']
        except:
            self.logger.error(f'can not get claims from https://www.wikidata.org/wiki/{wdid}')
            self.pp.pprint(entity['claims'])

            quit()

    def get_upper_location_wdid(self, wdobj):
        if 'P131' in wdobj['claims']:
            return self.get_best_claim(wdobj['id'], 'P131')
            # return self.get_wd_by_wdid(wdobj['claims']['P131'][0]['value'])

        return None

    def normalize_wdid(self, object_wdid: str) -> str:
        # convert Q1021645#office_building to Q1021645
        if '#' not in object_wdid:
            return object_wdid
        else:
            return object_wdid[0:object_wdid.find('#')]

    def get_settlement_for_object(self,location_wdid, verbose=False)->str:
        """
        for wikidata object run by P131 properties and find its settlement object
        return None if not found
        """
        location_wdid = self.normalize_wdid(location_wdid)
        cache_key = location_wdid
        if cache_key in self.cache_settlement_for_object:
            return self.cache_settlement_for_object[cache_key]
        stop_hieraechy_walk = False
        cnt = 0
        geoobject_wd = self.get_wikidata_simplified(location_wdid)
        settlements_ids = self.get_settlements_wdids()
        while not stop_hieraechy_walk:
            cnt = cnt+1
            if cnt > 9:
                stop_hieraechy_walk = True
            if verbose:
                print('check if settlement is '+geoobject_wd['labels'].get('en',' no english name'))
            # is one of p31 is settlements?
            for instance in  geoobject_wd["claims"]["P31"]:
                if instance['value'] in  settlements_ids:
                    if verbose:
                        print('this is settlement')
                    self.cache_settlement_for_object[cache_key]=geoobject_wd['id'] 
                    return geoobject_wd['id']  

            upper_wdid = self.get_upper_location_wdid(geoobject_wd)
            if upper_wdid is None:
                stop_hieraechy_walk = True
                return None
            geoobject_wd = self.get_wikidata_simplified(upper_wdid)
            

    def get_category_object_in_location(self, object_wdid, location_wdid, order: str = None, verbose=False) -> str:
        object_wdid = self.normalize_wdid(object_wdid)
        cache_key = str(object_wdid)+'/'+location_wdid
        if cache_key in self.cache_category_object_in_location:
            text = ''+self.cache_category_object_in_location[cache_key]+''
            if order:
                text = text+'|'+order
            return text
        stop_hieraechy_walk = False
        cnt = 0
        object_wd = self.get_wikidata_simplified(object_wdid)
        geoobject_wd = self.get_wikidata_simplified(location_wdid)
        while not stop_hieraechy_walk:
            cnt = cnt+1
            if cnt > 9:
                stop_hieraechy_walk = True
            if verbose:
                info = 'search category for union ' + \
                    str(object_wd['labels'].get('en', object_wd['id']))+' ' + \
                    str(geoobject_wd['labels'].get(
                        'en', geoobject_wd['id'])[0:35].rjust(35))
                print(info)
                # self.logger.info(info)

            # search category "objects in city/country" by name
            if object_wd.get('commons') is not None and geoobject_wd.get('commons') is not None:
                suggested_category=object_wd['commons'] + ' in '+geoobject_wd['commons']
                if self.is_category_exists(suggested_category):
                    text=suggested_category
                    if order:
                        text = text+'|'+order
                    return text

            # search category by wikidata
            union_category_name = self.search_commonscat_by_2_wikidata(
                object_wdid, geoobject_wd['id'])
            if union_category_name is not None:
                print('found ' + '[[Category:'+union_category_name+']]')
                self.cache_category_object_in_location[cache_key] = union_category_name
                text = ''+union_category_name+''
                if order:
                    text = text+'|'+order
                return text

            upper_wdid = self.get_upper_location_wdid(geoobject_wd)
            if upper_wdid is None:
                stop_hieraechy_walk = True
                continue
            upper_wd = self.get_wikidata_simplified(upper_wdid)
            geoobject_wd = upper_wd

        return None

    def append_image_descripts_claim(self, commonsfilename, entity_list, dry_run=False)->bool:

        assert isinstance(entity_list, list)
        assert len(entity_list) > 0
        if dry_run:
            print('simulate add entities')
            self.pp.pprint(entity_list)
            return
        from fileprocessor import Fileprocessor
        fileprocessor = Fileprocessor()
        commonsfilename = fileprocessor.prepare_commonsfilename(
            commonsfilename)

        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        page = pywikibot.Page(site, title=commonsfilename, ns=6)
        media_identifier = "M{}".format(page.pageid)

        # fetch exist structured data

        request = site.simple_request(
            action="wbgetentities", ids=media_identifier)
        try:
            raw = request.submit()
        except:
            self.logger.error(traceback.format_exc())
            return None

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

        return True

    def wikidata_set_building_entity_name(self, wdid, city_wdid):
        '''
        change names and aliaces of wikidata entity for building created by SNOW tool: https://ru-monuments.toolforge.org/snow/index.php?id=6330122000

        User should manually enter LOCATED ON STREET with HOUSE NUMBER

        Source:
        https://www.wikidata.org/wiki/Q113683138
        Жилой дом (Тверь)

        Result:
        name ru     Тверь, улица Достоевского 30
        name en     Tver Dostoevskogo street 30
        alias (ru)  [Жилой дом (Тверь)]

        '''
        site = pywikibot.Site("wikidata", "wikidata")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        item = pywikibot.ItemPage(site, wdid)
        item.get()
        
        city_wd = self.get_wikidata_simplified(city_wdid)

        assert ('ru' in item.labels)
        assert 'P669' in item.claims, 'you should set P669 en at https://www.wikidata.org/wiki/'+wdid+''
        claims = item.claims.get("P669")

        # GET BEST CLAIM 
        best_claim=None
        for claim in claims:
            if claim.rank=='preferred':
                best_claim=claim
                break
        if best_claim is None:
            best_claim=claims[0]
        claim = best_claim
        del best_claim


        street_id = claim.getTarget().id
        try:
            street_name_en = claim.getTarget().labels['en']
        except:
            raise ValueError(
                'you should set label en at https://www.wikidata.org/wiki/'+claim.getTarget().id+'')
            quit()
        street_name_ru = claim.getTarget().labels['ru']

        # Get the qualifiers of P670
        qualifiers = claim.qualifiers.get("P670")

        # Loop through the qualifiers
        for qualifier in qualifiers:
            # Print the postal code value
            housenumber = qualifier.getTarget()

        self.logger.info(f'{street_name_en} {street_name_ru} {housenumber}')


        entitynames = dict()
        labels = dict()
        change_langs=dict()
        new_label = self.address_international(city='',street=street_name_en, housenumber=housenumber).strip()
        if len(item.labels.get('en','')) < 50 and len(item.labels.get('en','')) > 6: new_label=new_label+', '+item.labels['en']
        if new_label != item.labels.get('en',''):
            labels['en'] = new_label
            change_langs['en']=True
        
        new_label = street_name_ru+' '+housenumber
        if len(item.labels.get('ru','')) < 50 and len(item.labels.get('ru','')) > 6: new_label=new_label+', '+item.labels['ru']
        if new_label != item.labels.get('ru',''): 
            labels['ru'] = new_label
            change_langs['ru']=True
        
        # move names to aliaces
        aliases = item.aliases
        if 'ru' not in aliases:
            aliases['ru'] = list()
        if 'en' not in aliases:
            aliases['en'] = list()
        if change_langs.get('ru')==True:
            aliases['ru'].append(item.labels['ru'])
        if 'en' in item.labels:
            if change_langs.get('en')==True:
                aliases['en'].append(item.labels['en'])
        item.editAliases(aliases=aliases, summary="Move name to alias")
        
        item.editLabels(
            labels=labels, summary="Set name from address P669+P670")
        item.editDescriptions(
            descriptions={"en": "Building in "+city_wd['labels']['en']}, summary="Edit description")
        
        self.reset_cache()

        return


    def create_wikidata_object_for_bylocation_category(self, category, wikidata1, wikidata2):
        assert category.startswith(
            'Category:'), 'category should start with Category:  only'
        assert wikidata1.startswith('Q'), 'wikidata1 should start from Q only'
        assert wikidata2.startswith('Q'), 'wikidata2 should start from Q only'
        category_name = category.replace('Category:', '')

        site = pywikibot.Site("wikidata", "wikidata")
        repo = site.data_repository()
        new_item = pywikibot.ItemPage(site)
        label_dict = {"en": category_name}
        new_item.editLabels(labels=label_dict, summary="Setting labels")

        # CLAIM
        claim = pywikibot.Claim(repo, 'P31')
        # This is Wikimedia category
        target = pywikibot.ItemPage(repo, "Q4167836")
        claim.setTarget(target)  # Set the target value in the local object.
        # Inserting value with summary to Q210194
        new_item.addClaim(claim, summary='This is 	Wikimedia category')
        del claim
        del target

        # CLAIM
        claim = pywikibot.Claim(repo, 'P971')
        # category combines topics
        target = pywikibot.ItemPage(repo, wikidata1)
        claim.setTarget(target)  # Set the target value in the local object.
        # Inserting value with summary to Q210194
        new_item.addClaim(claim, summary='This is 	Wikimedia category')
        claim = pywikibot.Claim(repo, 'P971')
        # category combines topics
        target = pywikibot.ItemPage(repo, wikidata2)
        claim.setTarget(target)  # Set the target value in the local object.
        # Inserting value with summary to Q210194
        new_item.addClaim(claim, summary='This is 	Wikimedia category')

        # SITELINK
        sitedict = {'site': 'commonswiki', 'title': category}
        new_item.setSitelink(sitedict, summary=u'Setting commons sitelink.')
        wikidata_id = new_item.getID()

        # ADD Wikidata infobox to commons
        site = pywikibot.Site("commons", "commons")
        site.login()
        site.get_tokens("csrf")  # preload csrf token
        pagename = self.page_name_canonical(category)
        page = pywikibot.Page(site, title=pagename)

        commons_pagetext = page.text
        if '{{Wikidata infobox}}' not in commons_pagetext:
            commons_pagetext = "{{Wikidata infobox}}\n"+commons_pagetext
        page.text = commons_pagetext
        page.save('add {{Wikidata infobox}} template')

    
    def is_subclass_of_building(self, wikidata_id:str)-> bool:
        return self.is_subclass_of(wikidata_id,'Q41176')
    
    def is_subclass_of(self,wikidata_id:str,class_wdid:str)-> bool:
        import requests
        # construct the SPARQL query using the wikidata id
        query = f"""
        ASK {{
            wd:{wikidata_id} wdt:P31*/wdt:P279* wd:{class_wdid}. # объект является экземпляром здания или его подкласса
        }}
        """
        # define the endpoint and the headers for the Wikidata query service
        endpoint = "https://query.wikidata.org/sparql"
        headers = {"Accept": "application/json"}
        # make a GET request with the query as a parameter
        response = requests.get(endpoint, params={"query": query}, headers=headers)
        # check if the response is successful
        if response.status_code == 200:
            # parse the JSON response and get the boolean value
            data = response.json()
            result = data["boolean"]
            # return the result
            return result
        else:
            # handle the error
            print(f"Error: {response.status_code}")
            return None

    def pagename_from_id(self,id:str)->str:
        '''
        id: digit
        '''
        if id.startswith('https://commons.wikimedia.org/entity/M'):
            id=id.replace('https://commons.wikimedia.org/entity/M','')
        if id.startswith('M'):
            id=id.replace('M','')
        site = pywikibot.Site('commons', 'commons') # create a Site object for Wikimedia Commons
        pages = pagegenerators.PagesFromPageidGenerator([id], site) # create a page generator with the page ID
        for page in pages: # iterate over the pages
            return page.title() # print the full page title

    def search_commonscat_by_2_wikidata(self, abstract_wdid, geo_wdid):
        if abstract_wdid==geo_wdid:
            return None
        if abstract_wdid in self.wikidata_cache['commonscat_by_2_wikidata']:
            if geo_wdid in self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid]:
                return self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid][geo_wdid]

        sample = """
                        SELECT DISTINCT ?item ?itemLabel WHERE {
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE]". }
  {
    SELECT DISTINCT ?item WHERE {
      ?item p:P971 ?statement0.
      ?statement0 (ps:P971) wd:Q22698.
      ?item p:P971 ?statement1.
      ?statement1 (ps:P971) wd:Q649.
    }
    LIMIT 100
  }
}

        """

        template = '''
        SELECT DISTINCT ?item ?itemLabel WHERE {
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE]". }
  {
    SELECT DISTINCT ?item WHERE {
      ?item p:P971 ?statement0.
      ?statement0 (ps:P971) wd:$SUBJECT.
      ?item p:P971 ?statement1.
      ?statement1 (ps:P971) wd:$COUNTRY.
    }
    LIMIT 100
  }
}
'''
        sparql = template
        sparql = sparql.replace('$SUBJECT', abstract_wdid)
        sparql = sparql.replace('$COUNTRY', geo_wdid)

        site = pywikibot.Site("wikidata", "wikidata")
        repo = site.data_repository()

        generator = pagegenerators.PreloadingEntityGenerator(
            pagegenerators.WikidataSPARQLPageGenerator(sparql, site=repo))
        for item in generator:
            item_dict = item.get()
            commonscat = None
            try:
                commonscat = item.getSitelink('commonswiki')
            except:
                claim_list = item_dict["claims"].get('P373', ())
                assert claim_list is not None, 'https://www.wikidata.org/wiki/' + \
                    abstract_wdid + ' must have P373'
                for claim in claim_list:
                    commonscat = claim.getTarget()
            assert commonscat is not None, 'invalid entity '+str(item) + "\n"+sparql
            commonscat = commonscat.replace('Category:', '')

            if abstract_wdid not in self.wikidata_cache['commonscat_by_2_wikidata']:
                self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid] = {
                }
            self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid][geo_wdid] = commonscat
            self.wikidata_cache_save(
                self.wikidata_cache, self.wikidata_cache_filename)
            return commonscat
        if abstract_wdid not in self.wikidata_cache['commonscat_by_2_wikidata']:
            self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid] = {}
        self.wikidata_cache['commonscat_by_2_wikidata'][abstract_wdid][geo_wdid] = None
        self.wikidata_cache_save(
            self.wikidata_cache, self.wikidata_cache_filename)
        return None