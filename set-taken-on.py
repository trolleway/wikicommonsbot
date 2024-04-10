#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, subprocess, logging, argparse, sys, pprint, datetime
import pywikibot

#import trolleway_commons
from model_wiki import Model_wiki
from fileprocessor import Fileprocessor
from urllib.parse import urlparse


parser = argparse.ArgumentParser(
    description=" ")

group = parser.add_mutually_exclusive_group()

group.add_argument('--pagename', type=str, required=False, help='Wikipedia filepage')
group.add_argument('--category', type=str, required=False, help='Wikipedia filepage')


parser.add_argument('--levels', type=int, required=False, help='sublevels', default=0)
parser.add_argument('--skip-location', type=str, required=False, help='if file already have this location, do not changes', default='')
parser.add_argument('--location', type=str, required=True)
parser.add_argument('--interactive', type=bool, required=False,default=False)



if __name__ == '__main__':
    
    args = parser.parse_args()
    #processor = trolleway_commons.CommonsOps()
    modelwiki = Model_wiki()


    if args.pagename:
        modelwiki.url_add_template_taken_on(pagename=args.pagename, location=args.location,verbose=True,interactive=args.interactive)
    elif args.category:
        modelwiki.category_add_template_taken_on(categoryname=args.category, location=args.location,dry_run=False,interactive=args.interactive,levels=args.levels, skip_location=args.skip_location)
        
    
    
    
    
    
    