import os
import re
import md5
import sys
import math
import logging

from datetime import datetime
from operator import itemgetter

import colors     # from nodebox
import feedparser
import flickrapi
import simplejson
from jinja2 import FileSystemLoader, Environment
from utilities import sessions

from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.api import urlfetch

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

# jinja2
env = Environment(extensions=['jinja2.ext.loopcontrols'],
                  loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/')))

class IndexPage(webapp.RequestHandler):
  def get(self, who=""):
    session = get_session()

    # session objects don't support has_key. bah.
    try:
      permanent = session['dopplr']
      token     = session['flickr']
    except KeyError, e:
      return self.redirect("/login/")

    stats           = {}
    
    # easter egg
    if (self.request.get('hel')):
      hel = True
    else:
      hel = False
    
    # TODO deboilerplate
    trips_info      = get_trips_info(permanent, who)
    if not trips_info:
      return error_page(self, session, "Your past trips could not be loaded.")
    if trips_info.has_key('error'):
      return error_page(self, session, trips_info['error'])

    traveller_info  = get_traveller_info(permanent, who)
    if not traveller_info:
      return error_page(self, session, "Your past trips could not be loaded.")
    if traveller_info.has_key('error'):
      return error_page(self, session, traveller_info['error'])

    # TODO ajax/memcache
    stats           = build_stats(trips_info['trip'], traveller_info, 'front')
    if hel:
      stats           = build_stats(trips_info['trip'], traveller_info, 'helvetica')
    
    template_values = {
      'session':    session,
      'permanent':  permanent,
      'traveller':  traveller_info,
      'trips':      trips_info['trip'],
      'stats':      stats,
      'numbers':    get_numbers(),
      'memcache':   memcache.get_stats(),
    }
    
    template = env.get_template('index.html')
    if hel:
      template = env.get_template('helvetica.html')
    
    self.response.out.write(template.render(template_values))

class StatsPage(webapp.RequestHandler): # TODO DRY
  def get(self, who=""):
    session = get_session()

    # session objects don't support has_key. bah.
    try:
      permanent = session['dopplr']
      token     = session['flickr']
    except KeyError, e:
      return self.redirect("/login/")

    stats           = {}
    
    # TODO deboilerplate
    trips_info      = get_trips_info(permanent, who)
    if not trips_info:
      return error_page(self, session, "Your past trips could not be loaded.")
    if trips_info.has_key('error'):
      return error_page(self, session, trips_info['error'])

    traveller_info  = get_traveller_info(permanent, who)
    if not traveller_info:
      return error_page(self, session, "Your past trips could not be loaded.")
    if traveller_info.has_key('error'):
      return error_page(self, session, traveller_info['error'])

    stats           = build_stats(trips_info['trip'], traveller_info, 'detail')
    
    template_values = {
      'session':    session,
      'permanent':  permanent,
      'traveller':  traveller_info,
      'trips':      trips_info['trip'],
      'stats':      stats,
      'numbers':    get_numbers(),
      'memcache':   memcache.get_stats(),
    }
    
    template = env.get_template('overview.html')
    
    self.response.out.write(template.render(template_values))

class TripPage(webapp.RequestHandler):
  def get(self, trip_id, type="", page="1"):
    session = get_session()

    try:
      permanent = session['dopplr']
      token     = session['flickr']
    except KeyError, e:
      return self.redirect("/login/")

    # get trip id and hence info from Dopplr
    if not trip_id or trip_id == "undefined":
      return self.redirect("/")

    trip_info = get_trip_info(permanent, trip_id)
    if trip_info.has_key('error'):
      return error_page(self, session, trip_info['error'])

    who = ""
    if session["nick"] != trip_info["nick"]:
      who = trip_info["nick"]
      # TODO traveller info (sigh)

    logging.info("who: '"+who+"'")

    trips_info = get_trips_info(permanent, who)
    if trips_info.has_key('error'):
      return error_page(self, session, trips_info['error'])

    links = links_for_trip(trips_info, trip_id)
        
    # initialise template data before we call Flickr
    template_values = {
      'session':    session,
      'trip':       trip_info,
      'links':      links,
      'keys':       get_keys(self.request.host),
    }
  
    if session["nick"] == trip_info["nick"]:
      if token and not trip_info["status"] == "Future":
        # get keys
        keys = get_keys(self.request.host)
        flickr = get_flickr(keys, token)      

        nsid = get_flickr_nsid(flickr, token)
        if nsid:
          template_values['prevpage'] = int(page)-1
          template_values['nextpage'] = int(page)+1
  
          if type == 'date':  
            template_values['photos'] = get_flickr_photos_by_date(flickr, nsid, trip_info, page)
            template_values['method'] = "date"
          elif type == 'tag':
            template_values['photos'] = get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page)
            template_values['method'] = "tag"
          else:
            photos = get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page)
            if photos and photos.has_key('total') and photos['total']:
              template_values['photos'] = photos
              template_values['method'] = "tag"
            else:
              template_values['photos'] = get_flickr_photos_by_date(flickr, nsid, trip_info, page)
              template_values['method'] = "date"

        else:
          return error_page(self, session, "Could not get info about the user data from Flickr.")     

    template_values['memcache'] = memcache.get_stats(),

    path = os.path.join(os.path.dirname(__file__), 'templates/trip.html')
    self.response.out.write(template.render(path, template_values))    

class SetsPage(webapp.RequestHandler):
  def get(self, page="1"):
    logging.debug("really in Add page")
    session = get_session()

    page = int(page)

    # session objects don't support has_key. bah.
    # TODO DRY
    try:
      permanent = session['dopplr']
      token     = session['flickr']
    except KeyError, e:
      return self.redirect("/login/")

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token)

    template_values = {
      'session':    session,
      'permanent':  permanent,
      'memcache':   memcache.get_stats(),
    }

    nsid = get_flickr_nsid(flickr, token)
    if nsid:
      logging.debug("getting set list")
      sets = get_flickr_setlist(flickr, nsid)

      if sets and sets.has_key('photosets'):
        sets = get_paged_setlist(sets, page)
      else:
        return error_page(self, session, "Could not get info about sets from Flickr.")     
      
      sets = get_sets_details(flickr, sets)
      template_values['sets'] = sets['photosets']
    else:
      return error_page(self, session, "Could not get info about the user data from Flickr.")     
 
    # jinja2
    template = env.get_template('sets.html')
    self.response.out.write(template.render(template_values))

class SetPage(webapp.RequestHandler):
  def get(self, set_id):
    logging.debug("Set page")
    session = get_session()

    # session objects don't support has_key. bah.
    # TODO DRY (decorator?)
    try:
      permanent = session['dopplr']
      token     = session['flickr']
    except KeyError, e:
      return self.redirect("/login/")

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token)

    template_values = {
      'session':    session,
      'permanent':  permanent,
      'memcache':   memcache.get_stats(),
    }

    nsid = get_flickr_nsid(flickr, token)
    if nsid:
      logging.debug("getting set list")
      sets = get_flickr_setlist(flickr, nsid)
      
      if not sets or not sets.has_key('photosets'):
        return error_page(self, session, "Could not get info about sets from Flickr.")     
      
      for set in sets['photosets']['photoset']:
        if set['id'] == set_id:
          template_values['metadata'] = set
          break

      logging.debug("getting set details")
      photoset = get_set_details(flickr, set_id, True)

      if not photoset or not photoset.has_key('photoset'):
        return error_page(self, session, "Could not get info about the set from Flickr.")     

      # add metadata
      photoset['photoset'] = get_flickr_date_range(photoset['photoset'], True)
      if not photoset['photoset'].has_key('trip_ids'):
        photoset['photoset'] = get_flickr_trip_ids(permanent, photoset['photoset'])

      photos = photoset['photoset']
      photos['subtotal'] = len(photos['photo'])

      photos = get_flickr_geototal(photos)
      if photoset['photoset'].has_key('trip_id'):
        photos = get_flickr_tagtotal(photos, photoset['photoset']['trip_id'])
      else:
        template_values['trip_ids'] = get_potential_trips(permanent, photoset['photoset'])
        
          # also get trip info for template?
#       if photoset['photoset'].has_key('trip_ids'):
#         for trip_id in photoset['photoset']['trip_ids'].keys():
#           photos = get_flickr_tagtotal(photos, trip_id)
#           # also get trip info for template?

      photoset['photoset'] = photos
      template_values['set'] = photoset['photoset']

    else:
      return error_page(self, session, "Could not get info about the user data from Flickr.")     
 
    # jinja2
    template = env.get_template('set.html')
    self.response.out.write(template.render(template_values))

class LoginPage(webapp.RequestHandler):
  def get(self):
    session = get_session()

    callback_url = "http://"+self.request.host+"/login/" 
  
    dopplr_url = "https://www.dopplr.com/api/AuthSubRequest?scope=http://www.dopplr.com&next="+callback_url+"&session=1"
    dopplr_token = self.request.get('token')

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys)      
    flickr_url = flickr.web_login_url('write')
    
    got_token = False
    token = self.request.get('token') # from Dopplr
    frob  = self.request.get('frob')  # from Flickr

    # get blog
    try:
      atom = urlfetch.fetch("http://blech.vox.com/library/posts/tags/snaptrip/atom-full.xml")
      feed = feedparser.parse(atom.content)
      # trim to just two
      feed['entries'] = feed['entries'][0:2]
      for entry in feed['entries']:
        entry['published_date'] = datetime( *entry.published_parsed[:-3] )
        entry['link']           = re.sub('\?.*$', '', entry['link'])

    except:
      feed = ""

    if token:
      response = urlfetch.fetch(
                   url = "https://www.dopplr.com/api/AuthSubSessionToken",
                   headers = {'Authorization': 'AuthSub token="'+token+'"'},
                 )
      match = re.search('Token=(.*)\n', response.content)
      if (match):
        permanent = match.group(1)
 
        # use this to store the traveller info
        dopplr_info = get_traveller_info(permanent)
        if dopplr_info.has_key('error'):
          return error_page(self, session, dopplr_info['error'])

        session['dopplr'] = permanent
        session['name'] = dopplr_info['name']        
        session['nick'] = dopplr_info['nick']        
        got_token = True
        # self.redirect("/")
    
    if frob:
      try:
        permanent = flickr.get_token(frob)
      except:
        return error_page(self, session, "The authentication token was out of date. Please try again.")
      if permanent:
        session['flickr'] = permanent
        got_token = True
        # self.redirect("/")

    try:
      if got_token and session['flickr'] and session['dopplr']:
        return self.redirect("/")
    except:
      logging.info("Not yet ready to visit trip list")

    template_values = {
      'dopplr_url': dopplr_url,
      'flickr_url': flickr_url,
      'frob':       frob,
      'session':    session,
      'keys':       keys,
      'feed':       feed,
    }
    
    path = os.path.join(os.path.dirname(__file__), 'templates/login.html')
    self.response.out.write(template.render(path, template_values))

class FormPage(webapp.RequestHandler):
  def get(self):
    session = get_session()

    template_values = {
      'session':    session,
    }

    path = os.path.join(os.path.dirname(__file__), 'templates/form.html')
    self.response.out.write(template.render(path, template_values))

  def post(self):
    session = get_session()
    name = self.request.get("name")
    text = self.request.get("text")

    sent = False
    error = ''

    email = ''
    try:
      traveller = get_traveller_info(session['dopplr'])
      email = traveller['email']
    except KeyError, e:
      email = ''
      
    if name and text:
      sent = True;  
      # send
      message = mail.EmailMessage(subject='snaptrip feedback (via form)',)
      message.sender = "misonp@googlemail.com"
    
      message.to = "Paul Mison <misonp@googlemail.com>"
      if email:
        message.cc = name+" <"+email+">"
        
      message.body = "The following is feedback about snaptrip.\n\n"+text;
      message.send()
    else:
      error = "You must enter a name and some feedback."
  
    template_values = {
      'name':       name,
      'text':       text,
      'error':      error,
      'sent':       sent,
      'session':    session,
    }

    path = os.path.join(os.path.dirname(__file__), 'templates/form.html')
    self.response.out.write(template.render(path, template_values))
    
# == AJAX

class MoreJSON(webapp.RequestHandler):
  def get(self):
    logging.error("deprecated MoreJSON handler called")

    token = self.request.get("token")
    nsid = self.request.get("nsid")
    page = self.request.get("page")

    if not token or not nsid:
      return self.response.out.write({'error': 'There was no Flickr token or NSID.'})

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token)

    if self.request.get("tripid", ""):
      machine_tag = "dopplr:trip="+self.request.get("tripid")

      logging.info("machine tag with '"+machine_tag+"'")

      json = flickr.photos_search(
                 format='json',
                 nojsoncallback="1",
                 user_id=nsid,
                 sort="date-taken-asc",
                 tags=machine_tag,
                 page=page,
                 per_page="24",
                 extras='geo, tags' # license, date_upload, date_taken, o_dims, views, media',
  #                privacy_filter="1",
               )
  
      self.response.out.write(json)

    if self.request.get("startdate", ""):
      startdate = self.request.get("startdate")+" 00:00:01"
      finishdate = self.request.get("finishdate")+" 23:59:59"

      logging.info("dates from '"+startdate+"' to '"+finishdate+"'")

      json = flickr.photos_search(
                 format='json',
                 nojsoncallback="1",
                 user_id=nsid,
                 sort="date-taken-asc",
                 min_taken_date=startdate,
                 max_taken_date=finishdate,
                 page=page,
                 per_page="24",
                 extras='geo, tags' # license, date_upload, date_taken, o_dims, views, media',
  #                privacy_filter="1",
               )
  
      self.response.out.write(json)

class TagJSON(webapp.RequestHandler):
  def get(self):
    token = self.request.get("token")

    if not token:
      return self.response.out.write({'error': 'There was no Flickr token.'})

    photo_id = self.request.get("photo_id")
    trip_id = self.request.get("trip_id")
    woe_id = self.request.get("woe_id")

    logging.info("Got token "+token+", photo_id "+photo_id+" and trip id '"+trip_id+"'")

    if not photo_id or not trip_id or not woe_id:
      logging.warn("Missing photo_id, trip_id or woe_id")
      return self.response.out.write({'error': 'There were missing parameters.'})

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token, True)

    try:
      json = flickr.photos_addTags(
                 format='json',
                 nojsoncallback="1",
                 photo_id=photo_id,
                 tags="dopplr:trip="+trip_id+" dopplr:woeid="+woe_id+" dopplr:tagged=snaptrip",
                )
      test = simplejson.loads(json) # check it's valid JSON

      if (self.request.get("nsid")):
        key = repr(flickr)+":nsid="+self.request.get("nsid")+":tripid="+str(trip_id)+":page="+self.request.get("page")+":type="+self.request.get("method")
        if memcache.delete(key) != 2:
          logging.info("Key deletion failed; either network error or key missing");
    except:
      json = {'error': 'There was a problem contacting Flickr.'} # TODO 'message' not 'error' key
              
    logging.info("got json "+repr(json));

    self.response.out.write(json)

class GeoTagJSON(webapp.RequestHandler):
  def get(self):
    logging.info("in GeoTagJSON")
    token = self.request.get("token")

    if not token:
      return self.response.out.write({'error': 'There was no Flickr token.'})

    photo_id = self.request.get("photo_id")
    latitude = self.request.get("latitude")
    longitude = self.request.get("longitude")

    logging.info("Got token "+token+", latitude "+latitude+" and longitude "+longitude)

    if not photo_id or not latitude or not longitude:
      logging.warn("No photo_id or trip_id!")
      return self.response.out.write({'error': 'There were missing parameters.'})

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token, True)

    try:
      json = flickr.photos_geo_setLocation(
                 format='json',
                 nojsoncallback="1",
                 photo_id=photo_id,
                 lat=latitude,
                 lon=longitude,
                 accuracy=9,   # 'city'
                )
      test = simplejson.loads(json) # check it's valid JSON
      
      # remove memcache
      if (self.request.get("nsid")):
        key = repr(flickr)+":nsid="+self.request.get("nsid")+":tripid="+self.request.get("trip_id")+":page="+self.request.get("page")+":type="+self.request.get("method")
        logging.info("key:: "+key)
        if memcache.delete(key) != 2:
          logging.info("Key deletion failed; either network error or key missing");
    except:
      json = {'error': 'There was a problem contacting Flickr.'}

    logging.info("got json "+repr(json));

    self.response.out.write(json)

class SetJSON(webapp.RequestHandler):
  def get(self):
    logging.info("in SetJSON")

    session = get_session()
    
    try:
      token  = session['flickr']
      dopplr = session['dopplr']
    except KeyError, e:
      return self.response.out.write({'stat':'error', 'message': 'Could not get tokens from session.'})

    set_id = self.request.get("set_id")
    logging.info("Got token "+token+", set-id "+set_id)

    if not set_id:
      logging.warn("No set_id or trip_id!")
      return self.response.out.write({'stat':'error', 'message': 'There were missing parameters.'})

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token, True)

    photoset = get_set_details(flickr, set_id, True)

    key = repr(flickr)+":set_id="+set_id
#     photoset = memcache.get(key)
#     if photoset:
#       return self.response.out.write(simplejson.dumps(photoset))
# 
#     try:
#       json = flickr.photosets_getPhotos(
#                  format='json',
#                  nojsoncallback="1",
#                  photoset_id=set_id,
#                  extras='date_taken,date_upload,tags',
#                 )
#       photoset = simplejson.loads(json) # check it's valid JSON
#     except:
#       photoset = {'stat':'error', 'message': 'There was a problem contacting Flickr.'}
# 
#     photoset['photoset'] = get_flickr_date_range(photoset['photoset'])

    photoset['photoset'] = get_flickr_date_range(photoset['photoset'], True)
    photoset['photoset'] = get_flickr_trip_ids(dopplr, photoset['photoset'])

    photoset['trip_ids'] = get_potential_trips(dopplr, photoset['photoset'])

    if not memcache.add(key, photoset, 3600):
      logging.warning("memcache add for photoset failed")

    # convert dates to string reprs for JSON
    photoset['photoset']['startdate'] = str(photoset['photoset']['startdate'])
    photoset['photoset']['finishdate'] = str(photoset['photoset']['finishdate'])

    self.response.out.write(simplejson.dumps(photoset))

# == Dopplr

def get_traveller_info(token, who=""):
  key = "dopplr="+token+":info=traveller"
  if who:
    key += ":who="+who
  
  traveller_info = memcache.get(key)
  if traveller_info:
    return traveller_info
  
  url = "https://www.dopplr.com/api/traveller_info.js"
  if who:
    url += "?traveller="+who

  try:
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+token+'"'},
               )
  except:
    return {'error': "Couldn't download traveller info from Dopplr."}

  traveller_info = {}
  try:
    traveller_info = simplejson.loads(response.content)
    traveller_info = traveller_info['traveller']
  except ValueError:
    return {'error': "Didn't get a JSON response from Dopplr's traveller_info API"}

  if not memcache.add(key, traveller_info, 3600):
    logging.warning("memcache add for traveller_info failed")

  return traveller_info

def get_trips_info(token, who=""):
  key = "dopplr="+token+":info=trips"
  if who:
    key += ":who="+who

  trips_info = memcache.get(key)
  if trips_info:
    logging.info("memcache hit for trips_info for '"+key+"'")
    return trips_info

  url = "https://www.dopplr.com/api/trips_info.js"
  if who:
    url += "?traveller="+who

  try:
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+token+'"'},
               )
  except:
    return {'error': "Couldn't download info about trips from Dopplr."}

  trips_info = {}
  try:
    trips_info = simplejson.loads(response.content)
  except ValueError:
    return {'error': "Didn't get a JSON response from Dopplr's trips_info API."}

  ## postprocessing. do stats here too?
  if trips_info and trips_info.has_key('trip'):
    trips_info['trip'] = prettify_trips(trips_info['trip'])
  else:
    # TODO raise
    return {'error': "Could not get information about past trips (user permission?)."}

  if not memcache.add(key, trips_info, 3600):
    logging.warning("memcache add for trips_info failed")

  return trips_info

def get_trip_info_direct(token, trip_id):
  key = "dopplr="+token+":info=trip:tripid="+trip_id

  logging.info("getting trip_info directly from Dopplr")
  trips_info = memcache.get(key)
  if trips_info:
    logging.info("memcache hit")
    return trips_info

  url = "https://www.dopplr.com/api/trip_info.js?trip_id="+trip_id
  try:
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+token+'"'},
               )
  except:
    return {'error': "Couldn't download trip info from Dopplr."}

  trip_info = {}
  try:
    trip_info = simplejson.loads(response.content)
  except ValueError:
    return {'error': "Didn't get a JSON response from Dopplr's trip_info API"}
    
  if trip_info.get('error'):
    # not good. show to user?
    return {'error': trip_info['error']}

  logging.info("got trip, postprocessing")
  ## postprocessing - time consuming? seperate routine?
  # get who info
  match = re.search('trip/(.*?)/', trip_info["trip"]["url"])
  if (match):
    trip_info["trip"]["nick"] = match.group(1)

  # get date info
  start  = datetime.strptime(trip_info["trip"]["start"],  "%Y-%m-%d")
  trip_info["trip"]["startdate"]  = start
  
  finish = datetime.strptime(trip_info["trip"]["finish"], "%Y-%m-%d")
  trip_info["trip"]["finishdate"] = finish

  # find status of trip: ongoing/past/future
  now = datetime.now()
  if trip_info["trip"]["startdate"] < now:
    if trip_info["trip"]["finishdate"] > now:
      trip_info["trip"]["status"] = "Ongoing"
    else:
      trip_info["trip"]["status"] = "Past"
  else:
    trip_info["trip"]["status"] = "Future"

  if not memcache.add(key, trip_info['trip'], 3600):
    logging.warning("memcache add for trip_info failed")
    
  logging.info("returning trip info")
  logging.info(trip_info['trip'])
  return trip_info['trip']

def get_trip_info(token, trip_id):
  key = "dopplr="+token+":info=trip:tripid="+trip_id

  logging.info("looking for trip_id "+str(trip_id))

  trip_info = memcache.get(key)
  if trip_info:
    logging.info("memcache hit for key '"+key+"'")
    return trip_info

  trip_list = get_trips_info(token)
  trips = {}
  for trip in trip_list['trip']:
    key = "dopplr="+token+":info=trip:tripid="+str(trip['id'])

    # add 'nick' data to trip
    match = re.search('trip/(.*?)/', trip["url"])
    if (match):
      trip["nick"] = match.group(1)
    
    if trip:
      trips[key] = trip

    if int(trip_id) == trip["id"]:
      logging.info("matched trip id with trip in trip_list")
      trip_info = trip

  if not memcache.set_multi(trips, 3600):
    logging.warning("memcache set_multi for trip_info failed")

  if trip_info:
    return trip_info
  else:
    logging.info("didn't find trip in logged in users: calling direct")
    return get_trip_info_direct(token, trip_id)

# == Flickr

def get_flickr_nsid(flickr, token):
  key = repr(flickr)+":token="+token
  nsid  = memcache.get(key)
  if nsid is not None:
    return nsid

  # check token (and get nsid)
  try:
    auth = flickr.auth_checkToken(
              format='json',
              nojsoncallback="1",
           )
  except:
    logging.info("Could not fetch auth token")
    return None

  try:
    auth = simplejson.loads(auth)
  except:
    logging.info("Could not parse  '"+auth+"'")
    return None

  if auth.get("auth"):
    nsid = auth['auth']['user']['nsid']
    # username = auth.user.
    logging.info("Got Flickr user NSID "+nsid)

    if not memcache.add(key, nsid):
      logging.warning("memcache add for NSID failed")

    return nsid
  else:
    return None

def get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page):
  # TODO dedupe with get_flickr_photos_by_date
  key = repr(flickr)+":nsid="+nsid+":tripid="+str(trip_info["id"])+":page="+page+":type=tag"
  logging.info("memcache key is "+key);
  photos = memcache.get(key)
  if photos:
    logging.info("memcache hit")
    return photos
    
  logging.debug("Attempting photo search by tag (no cache)")

  machine_tag = "dopplr:trip="+str(trip_info["id"])
  logging.info("Got trip ID to search on: "+machine_tag);
 
  try:
    photos = flickr.photos_search(
               format='json',
               nojsoncallback="1",
               user_id=nsid,
               tags=machine_tag,
               sort="date-taken-asc",
               per_page="24",
               page=page,
               extras='geo, tags' # license, date_upload, date_taken, o_dims, views, media',
  #                privacy_filter="1",
             )
    photos = simplejson.loads(photos)
  except:
    return {'error': 'Could not get photos from Flickr using machine tag search.'}

  photos = photos['photos']
  photos = get_flickr_geototal(photos)
  photos = get_flickr_tagtotal(photos, trip_info["id"])

  if not memcache.add(key, photos, 3600):
    logging.warning("memcache add for photos by tag failed")

  return photos

def get_flickr_photos_by_date(flickr, nsid, trip_info, page):
  # TODO dedupe with get_flickr_photos_by_machinetag
  key = repr(flickr)+":nsid="+nsid+":tripid="+str(trip_info["id"])+":page="+page+":type=date"
  photos = memcache.get(key)
  if photos:
    return photos
    
  logging.debug("Attempting photo search by date (no cache)")

  # TODO right thing with times (which is...?)
  min_taken = trip_info["startdate"].strftime("%Y-%m-%d 00:00:01")
  max_taken = trip_info["finishdate"].strftime("%Y-%m-%d 23:59:59")

  # TODO dtrt with day ends (what did I mean here?)
  try:
    photos = flickr.photos_search(
               format='json',
               nojsoncallback="1",
               user_id=nsid,
               min_taken_date=min_taken,
               max_taken_date=max_taken,
               sort="date-taken-asc",
               per_page="24",
               page=page,
               extras='geo, tags' # license, date_upload, date_taken, o_dims, views, media',
  #                privacy_filter="1",
             )
    photos = simplejson.loads(photos)
  except:
    return {'error': 'Could not get photos from Flickr using date taken search.'}

  photos = photos['photos']
  photos = get_flickr_geototal(photos)
  photos = get_flickr_tagtotal(photos, trip_info["id"])

  if not memcache.add(key, photos, 3600):
    logging.warning("memcache add for photos by date failed")

  return photos

def get_flickr_setlist(flickr, nsid):
  key = repr(flickr)+":nsid="+nsid+":type=sets"
  sets = memcache.get(key)
  if sets:
    logging.info("memcache hit for setlist")
    return sets
    
  logging.info("Getting set list from Flickr")
  try:
    sets = flickr.photosets_getList(
               format='json',
               nojsoncallback="1",
               nsid=nsid, )
    sets = simplejson.loads(sets)
    if sets['stat'] == "ok":
      if not memcache.add(key, sets, 3600):
        logging.warning("memcache add for setlist failed")

    return sets

  except:
    logging.error("Error getting list of sets from Flickr")

  return {'message': 'Could not get list of sets from Flickr.'}  

def get_paged_setlist(sets, page):
  logging.info("getting page %s of setlist" % page);
  setsperpage = 10
  setcount   = len(sets['photosets']['photoset'])

  sets['photosets']['total'] = setcount
  sets['photosets']['pages'] = int(math.ceil(float(setcount)/setsperpage))
  sets['photosets']['page']  = page
  sets['photosets']['perpage'] = setsperpage
  
  if setcount > setsperpage:
    start = setsperpage*(page-1)
    end   = setsperpage*page
    sets['photosets']['photoset'] = sets['photosets']['photoset'][start:end]

  return sets;

def get_sets_details(flickr, sets):
  for set in sets['photosets']['photoset']:
    details = get_set_details(flickr, set['id'], False)
    if details:
      logging.info("fetched previously cached set details")
      set['dates']   = details['photoset']['dates']
      if details['photoset'].has_key('trip_id'):
        set['trip_id'] = details['photoset']['trip_id']
        set['trip_info'] = details['photoset']['trip_info']
  
  return sets

def get_set_details(flickr, set_id, ask_flickr=False):
  key = repr(flickr)+":set_id="+set_id

  photoset = memcache.get(key)
  if not photoset and ask_flickr:
    logging.info("fetching previously uncached set datails for key '"+key+"'")

    try:
      logging.debug("no cache, calling flickr.photosets.getPhotos with set_id "+set_id)
      json = flickr.photosets_getPhotos(
                 format='json',
                 nojsoncallback="1",
                 photoset_id=set_id,
                 extras='geo,date_taken,date_upload,tags',
#                 extras='date_taken,date_upload,tags',
                )
      logging.debug("got response '"+json+"'")
      photoset = simplejson.loads(json) # check it's valid JSON
    except:
      photoset = {'stat':'error', 'message': 'There was a problem contacting Flickr.'}

  return photoset

def get_flickr_geototal(photos):
  photos['subtotal'] = 0
  photos['geototal'] = 0
  for photo in photos['photo']:
    photos['subtotal'] = photos['subtotal'] +1
    if photo['latitude'] and photo['longitude']:
      photos['geototal'] = photos['geototal']+1
      if int(photo['accuracy']) > 9:
        photo['accurate'] = True

  # if we want this as a string (we don't)
  # photos['geototal'] = str(photos['geototal'])

  return photos

def get_flickr_tagtotal(photos, trip_id):
  photos['tagtotal'] = 0
  for photo in photos['photo']:

    if photo['tags'].find('dopplr:trip='+str(trip_id)) > 0:
      photos['tagtotal'] += 1
      photo['dopplr'] = True;

  if photos['tagtotal']:
    photos['totag']    = str(int(photos['subtotal'])-photos['tagtotal'])
  else:
    photos['totag']    = photos['subtotal']
  photos['tagtotal'] = str(photos['tagtotal'])

  return photos

def get_flickr_date_range(photos, dates=False):
  start_date = None
  finish_date = None
  
  for photo in photos['photo']:
    datetaken = datetime.strptime(photo['datetaken'], "%Y-%m-%d %H:%M:%S")
    if not start_date or datetaken < start_date:
      start_date = datetaken
    if not finish_date or finish_date < datetaken:
      finish_date = datetaken

  if dates:
    photos['startdate']  = start_date
    photos['finishdate'] = finish_date

  start_day  = start_date.strftime("%d %B %Y")
  finish_day = finish_date.strftime("%d %B %Y")

  if start_day == finish_day:
    photos['dates'] = "taken on %s" % (start_day)
  elif start_date.month == finish_date.month and start_date.year == finish_date.year:
    photos['dates'] = "taken from %s to %s" % (start_date.strftime("%d"), finish_day)
  elif start_date.year == finish_date.year:
    photos['dates'] = "taken from %s to %s" % (start_date.strftime("%d %B"), finish_day)
  else:
    photos['dates'] = "taken from %s to %s" % (start_day, finish_day)

  # humanise
  photos['dates'] = photos['dates'].replace(" 0", " ")
  return photos

def get_flickr_trip_ids(dopplr, photos):
  trip_ids = {}

  for photo in photos['photo']:
    for m in re.finditer('dopplr:trip=(\d+)', photo['tags']):
      trip_id = m.group(1)
      if not trip_ids.has_key(trip_id):
        trip_ids[trip_id] = 1
      else:
        trip_ids[trip_id] += 1
    
  for trip_id in trip_ids:
    if trip_ids[trip_id] == photos['total']:
      photos['trip_id'] = trip_id
      trip_info = get_trip_info(dopplr, trip_id)
      photos['trip_info'] = { 'rgb': trip_info['city']['rgb'],
                              'name': trip_info['city']['name'],
                            }
      break # only take the first
  
  photos['trip_ids'] = trip_ids

  return photos

# == utilities

def error_page(self, session, error):
  path = os.path.join(os.path.dirname(__file__), 'templates/error.html')
  self.response.out.write(template.render(path, {'error':error, 'session':session, }))

def get_numbers():
  return ["no", "one", "two", "three", "four", "five", "six",
          "seven", "eight", "nine", "ten"]

def prettify_trips(trip_list):
  # parse dates to datetime objects
  now = datetime.now()
  
  for trip in trip_list:
    trip["startdate"]  = datetime.strptime(trip["start"],  "%Y-%m-%d")
    trip["finishdate"] = datetime.strptime(trip["finish"], "%Y-%m-%d")

    # find status of trip: ongoing/past/future
    if trip["startdate"] < now:
      if trip["finishdate"] > now:
        trip["status"] = "Ongoing"
      else:
        trip["status"] = "Past"
    else:
      trip["status"] = "Future"
      
  return trip_list
  
def get_potential_trips(dopplr, photos):
  trips_info = get_trips_info(dopplr)

  overlap_ids = []
  for trip in trips_info['trip']:
    if trip['startdate'] < photos['startdate'] \
       and trip['finishdate'] > photos['startdate']:
      overlap_ids.append(trip['id'])

  return overlap_ids

def links_for_trip(trips_list, trip_id):
  logging.debug("links_for_trip")
  # todo memcache (although this is relatively cheap)
  index = 0
  trip_index = 0
  city_index = 0

  logging.info(trip_id)
  logging.info(len(trips_list))

  ids = []
  cities = []
  status = []
  for trip in trips_list['trip']:
    ids.append(trip['id'])    
    cities.append(trip['city']['name'])
    status.append(trip['status'])
    
    if int(trip['id']) == int(trip_id):
      trip_index = index
      trip_city  = trip['city']['name']
    index = index+1

  if not trip_index:
    return {}

  index = 0
  city_ids = []
  for city in cities:
    if city == trip_city:
      id = ids[index]
      city_ids.append(id)
    index = index+1

  index = 0
  for id in city_ids:
    if int(id) == int(trip_id):
      city_index = index
    index = index+1

  links = {}

  if (trip_index > 0):
    links['prev'] = {'id':ids[trip_index-1], 'status':status[trip_index-1], 'city':cities[trip_index-1]}
  if (trip_index < len(ids)-1 and len(ids) > 1):
    links['next'] = {'id':ids[trip_index+1], 'status':status[trip_index+1], 'city':cities[trip_index+1]}
  if (city_index > 0):
    links['city_prev'] = {'id':city_ids[city_index-1], 'status':status[city_index-1],}
  if (city_index < len(city_ids)-1 and len(city_ids) > 1):
    links['city_next'] = {'id':city_ids[city_index+1], 'status':status[city_index-1],}
  links['city_ids'] = city_ids

  return links
  
def build_stats(trip_list, traveller_info, type):
  # TODO break this apart and/or do similar things in subroutines
  # TODO build more year metadata
  # TODO don't do as much work for front page
  # TODO cache?

  stats = {'countries': {},
           'cities':    {},
           'years':     {},
           'months':    {},
           'home':      { 'trips': 0, 'duration':0, },
           'away':      { 'trips': 0, 'duration':0, },
           'future':    0,
           'types':     {},
           'ordered':   {}, }

  if not trip_list:
    return stats
           
  # home_country = traveller_info['home_city']['country']
  
  for trip in trip_list:
    # skip if not a past trip
    if trip['status'] != "Past":
      if trip['status'] == "Ongoing":
        stats['current'] = trip['city']['name']
      else:
        stats['future'] += 1
      continue
      
    # how long (simple version...) # TODO never double count date
    duration = trip['finishdate'] - trip['startdate']
    trip['duration'] = duration.days
    
    # build country data
    country = trip['city']['country']
    display = country
    inline  = country

    # special casing!
    if not country.find("United"): # TODO there's something wrong here...
      inline = "the "+country      # TODO and this should be a hash anyway
    if not country.find("Hong Kong"):
      display = "Hong Kong"
      inline  = "Hong Kong"
    
    # stuff info into the data structure
    if not country in stats['countries']:
      stats['countries'][country] = { 'duration': 0, 'trips': 0, 
                                      'display':display, 'inline':inline,
                                      'code':trip['city']['country_code'], 
                                      'rgb':md5.new(country).hexdigest()[0:6]}

    stats['countries'][country]['duration'] += duration.days
    stats['countries'][country]['trips']    += 1

    if type != "front":
      if trip.has_key('return_transport_type'): # TODO remove
        if not trip['return_transport_type'] in stats['types']:
          stats['types'][trip['return_transport_type']] = {'trips':0, 'journeys':0, }
        stats['types'][trip['return_transport_type']]['trips'] += 0.5
        
      if trip.has_key('return_transport_type'): # TODO remove
        if not trip['outgoing_transport_type'] in stats['types']:
          stats['types'][trip['outgoing_transport_type']] = {'trips':0, 'journeys':0, }
        stats['types'][trip['outgoing_transport_type']]['trips'] += 0.5
 
        # if (country == home_country):
        #   stats['home']['trips'] += 1;
        #   stats['home']['duration'] += duration.days
        # else:
        #   stats['away']['trips'] += 1;
        #   stats['away']['duration'] += duration.days
  
    # build city data
    city = trip['city']['name']
    rgb  = trip['city']['rgb']

    if not city in stats['cities']:
      stats['cities'][city] = { 'duration': 0, 'trips': 0, 
                                'rgb':rgb, 'country':country, 
                                'id':trip['city']['woeid'], 
                                'trip_list': [], 'code':trip['city']['country_code']
                              }

    stats['cities'][city]['duration'] += duration.days
    stats['cities'][city]['trips']    += 1

    if type != "front":
      stats['cities'][city]['trip_list'].append(trip)
    
    # build year data
    year = trip['startdate'].year

    # initialise data structure's
    if not year in stats['years']:
      stats['years'][year] = { 'duration': 0, 'trips': 0, 'away':{}, 'home':{}, }
    if year == trip['finishdate'].year:
      stats['years'][year]['duration'] += duration.days
      stats['years'][year]['trips'] += 1
    else:
      if trip['finishdate'].year - year == 1:
        # spans a single year boundary, and is therefore Sane
        # if there's *anyone* who has a trip spanning two, they can bloody
        # well write this themselves. Otherwise, assume they mean they're
        # living there now. Onwards...

        year_end = datetime(year, 12, 31)
        
        stats['years'][year]['duration'] += (year_end-trip['startdate']).days
        stats['years'][year]['trips']    += 1
  
        year = trip['finishdate'].year
        year_start = datetime(year, 1, 1)
        if not year in stats['years']:
          stats['years'][year] = { 'duration': 0, 'trips': 0, 'away':{}, 'home':{}, }
        stats['years'][year]['duration'] += (trip['finishdate']-year_start).days
        # for now we don't count trips in both years. change?

    if type != "front":
      # do we care about finish months?
      month = trip['startdate'].month
      if not stats['months'].has_key(month):
        stats['months'][month] = {'trips':0, 'duration':0, 'cities':[]}
      stats['months'][month]['trips'] += 1
      stats['months'][month]['duration'] += duration.days
      stats['months'][month]['cities'].append(trip)

    # do we want to supply full-blown cross-cut stats? maybe later...
    # END TRIP LOOP
    
  # reorder final stats
  stats['ordered']['years'] = sorted(stats['years'])
  stats['ordered']['years'].reverse()

  stats['ordered']['types'] = sorted(stats['types'],          lambda x, y: (int(stats['types'][y]['trips']))-(int(stats['types'][x]['trips'])))

  stats['ordered']['years_by_trip'] = sorted(stats['years'],  lambda x, y: (stats['years'][y]['trips'])-(stats['years'][x]['trips']))
  stats['ordered']['years_by_days'] = sorted(stats['years'],  lambda x, y: (stats['years'][y]['duration'])-(stats['years'][x]['duration']))
  
  stats['ordered']['countries'] = sorted(stats['countries'],  lambda x, y: (stats['countries'][y]['duration'])-(stats['countries'][x]['duration']))
  stats['ordered']['cities']    = sorted(stats['cities'],     lambda x, y: (stats['cities'][y]['duration'])-(stats['cities'][x]['duration']))

  # colours
  if type != "front":
    rgb = stats['countries'][stats['ordered']['countries'][0]]['rgb']
    raw = colors.hex('#'+rgb)
    saturated = raw.saturate(1);
    lightened = saturated.lighten(0.5);
    desaturated = lightened.desaturate(0.8);
  
    stats['rgb']        = hex_from(lightened)
    stats['rgb_start']  = hex_from(desaturated)
  
    # scale country stats for map (including colours)
    top_country  = stats['ordered']['countries'][0]
    top_duration = stats['countries'][top_country]['duration']
    r = stats['rgb'][0:2]; g = stats['rgb'][2:4]; b = stats['rgb'][4:6]
    for country in stats['countries'].keys():
      scaled = 100*stats['countries'][country]['duration']/top_duration
  
      satscale = (float(100-scaled)/100)*0.8
      satcolor = lightened.desaturate(satscale)
  #     ligscale = (float(100-scaled)/100)*0.9
  #     ligcolor = saturated.lighten(ligscale)
  
      stats['countries'][country]['scaled'] = scaled
      stats['countries'][country]['rgb_scaled'] = hex_from(satcolor)
    
    # scale transport types
    if len(stats['types'].keys()):  # TODO remove
      top_type = stats['ordered']['types'][0]
      top_trip = int(stats['types'][top_type]['trips'])
      for type in stats['types'].keys():
        stats['types'][type]['scaled'] = 200*int(stats['types'][type]['trips'])/top_trip
        stats['types'][type]['journeys'] = int((stats['types'][type]['trips']*2))
        
    # scale years
    top_year_by_days = stats['ordered']['years_by_days'][0]
    top_year_days    = stats['years'][top_year_by_days]['duration']

  # scale years (for front page too)
  top_year_by_trip = stats['ordered']['years_by_trip'][0]
  top_year_trips   = stats['years'][top_year_by_trip]['trips']

  if type != "front":
    # width per trip scaling for years
    trips_per_block = 1
    while 90*trips_per_block/top_year_trips < 10:
      trips_per_block += 1
    
    stats['top_year_trips']  = top_year_trips
    stats['trips_per_block'] = trips_per_block
    stats['block_width']     = 90*trips_per_block/top_year_trips
  
    for year in stats['years']:
      if year == top_year_by_days:
        # TODO do this in template (the data's there...)
        stats['away']['days'] = (stats['years'][top_year_by_days]['duration'])/3.66
        stats['home']['days'] = (366-stats['years'][top_year_by_days]['duration'])/3.66
      stats['years'][year]['away']['days']     = (stats['years'][top_year_by_days]['duration'])/3.66
      stats['years'][year]['home']['days']     = (366-stats['years'][top_year_by_days]['duration'])/3.66
  
      # raw scaling
      stats['years'][year]['duration_scaled']  = int(220*stats['years'][year]['duration']/top_year_days)
      stats['years'][year]['trips_scaled']     = int(220*stats['years'][year]['trips']/top_year_trips)
  
      # block scaling
      stats['years'][year]['trips_blocks']     = float(stats['years'][year]['trips'])/stats['trips_per_block']
      stats['years'][year]['trips_blocks_l']   = [True] * (stats['years'][year]['trips']/stats['trips_per_block'])
      stats['years'][year]['trips_blocks_r']   = int((stats['years'][year]['trips_blocks']-len(stats['years'][year]['trips_blocks_l']))*stats['block_width'])

  return stats

def hex_from(color):
  return "%02x%02x%02x" % (int(color.r*255), int(color.g*255), int(color.b*255))

def get_display_names():
  return {
          'United States': { 'display': "the United States" },
          'United Kingdom': { 'display': "the United Kingdom" },
         }

def get_keys(host):
  keys = {}

  # get the right API keys for the current server. Thanks Tom.
  DEVELOPMENT = os.environ['SERVER_SOFTWARE'][:11] == 'Development'
  if DEVELOPMENT:
    keys = {
      'gmap':       "ABQIAAAAAuD6u2ORBgn25rPuxX1qxxTwM0brOpm-All5BF6PoaKBxRWWERQtnsYZp4mF-8WXCriNCoSun02Skw",
      'flickr_key': "d0f74bf817f518ae4ce7892ac7fce7de",
      'flickr_sec': "312fb375d41fcb09",
    }
  else:    
    keys = {
      'gmap':       "ABQIAAAAAuD6u2ORBgn25rPuxX1qxxQ4d34u_oYfzC9kAIhtljFln5QgnBSLj4qbVLSLA2cKssBO11cTRrUoXg",
      'flickr_key': "6e990ae1ba4697e88afa5d626b138fd2",
      'flickr_sec': "172d6389fecab4bd",
    }
    
  return keys

def get_flickr(keys, token='', disablecache=False):
  if disablecache:
    flickr = flickrapi.FlickrAPI(keys['flickr_key'], keys['flickr_sec'], 
                                 token=token, store_token=False)
    return flickr
  else:
    flickr = flickrapi.FlickrAPI(keys['flickr_key'], keys['flickr_sec'], 
                                 token=token, store_token=False, cache=True)
    flickr.cache = flickrapi.SimpleCache(timeout=300, max_entries=200)
    return flickr
  return  

def get_session():
  return sessions.Session(session_expire_time=10368000,)

# ==

application = webapp.WSGIApplication(
                  [('/', IndexPage),
                   ('/where/(\w*)', IndexPage),

                   ('/overview/', StatsPage),
                   ('/overview/(\w*)', StatsPage),

                   ('/sets/', SetsPage),
                   ('/sets/page/(\d+)', SetsPage),

                   ('/sets/set/(\d+)', SetPage),

                   ('/trip/(\d*)', TripPage),
                   ('/trip/(\d*)/by/(\w+)', TripPage),
                   ('/trip/(\d*)/by/(\w+)/(\d+)', TripPage),

                   ('/login/', LoginPage),
                   ('/form/', FormPage),

                   ('/ajax/photos.more', MoreJSON),
                   ('/ajax/photos.tag', TagJSON),
                   ('/ajax/photos.geotag', GeoTagJSON),
                   ('/ajax/photos.set', SetJSON),
                  ],
                  debug=True)

def main():
  run_wsgi_app(application)
  logging.getLogger().setLevel(logging.DEBUG)

if __name__ == "__main__":
  main()

# Class Dopplr():
#   def get(url, args):
#     response = urlfetch.fetch("https://www.dopplr.com/api/AuthSubSessionToken?token="+token)
#     return response.content