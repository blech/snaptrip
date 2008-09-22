import os
import re
import md5
import sys
import logging

from datetime import datetime
from operator import itemgetter

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
env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/')))

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
    trips_info      = get_trips_info(permanent, who)
    if trips_info.has_key('error'):
      return error_page(self, session, trips_info['error'])

    # TODO ajax/memcache
    if trips_info:
      stats         = build_stats(trips_info['trip'])
    
    template_values = {
      'session':    session,
      'permanent':  permanent,
      'traveller':  get_traveller_info(permanent, who),
      'trips':      trips_info['trip'],
      'stats':      stats,
      'memcache':   memcache.get_stats(),
    }
    
    path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
    template = env.get_template('index.html')
    
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

    # initialise template data before we call Flickr
    template_values = {
      'session':    session,
      'trip':       trip_info,
      'keys':       get_keys(self.request.host),
    }
  
    if session["nick"] == trip_info["trip"]["nick"]:
      if token and not trip_info["trip"]["status"] == "Future":
        # get keys
        keys = get_keys(self.request.host)
        flickr = get_flickr(keys, token)      

        nsid = get_flickr_nsid(flickr, token)
        if nsid:
          template_values['nextpage'] = int(page)+1
  
          if type == 'date':  
            template_values['photos'] = get_flickr_photos_by_date(flickr, nsid, trip_info, page)
            template_values['method'] = "date"
          elif type == 'tag':
            template_values['photos'] = get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page)
            template_values['method'] = "tag"
          else:
            photos = get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page)
            if photos and photos['total']:
              template_values['photos'] = photos
              template_values['method'] = "tag"
            else:
              template_values['photos'] = get_flickr_photos_by_date(flickr, nsid, trip_info, page)
              template_values['method'] = "date"

    template_values['memcache'] = memcache.get_stats(),

    path = os.path.join(os.path.dirname(__file__), 'templates/trip.html')
    self.response.out.write(template.render(path, template_values))    

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
    
      message.to = "Paul Mison <misonp+snaptrip@googlemail.com>"
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
    logging.error("deprecated")

    token = self.request.get("token")
    nsid = self.request.get("nsid")
    page = self.request.get("page")

    if not token or not nsid:
      return self.response.out.write({'error': 'There was no Flickr token.'})

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

  if not memcache.add(key, traveller_info):
    logging.error("set for traveller_info failed")

  return traveller_info

def get_trips_info(token, who=""):
  key = "dopplr="+token+":info=trips"
  if who:
    key += ":who="+who

  trips_info = memcache.get(key)
  if trips_info:
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
    return {'error': "Didn't get a JSON response from Dopplr's trips_info API"}

  ## postprocessing. do stats here too?
  if trips_info:
    trips_info['trip'] = prettify_trips(trips_info['trip'])

  if not memcache.add(key, trips_info):
    logging.error("set for trips_info failed")

  return trips_info

def get_trip_info(token, trip_id):
  key = "dopplr="+token+":info=trip:tripid="+trip_id

  trips_info = memcache.get(key)
  if trips_info:
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

  if not memcache.add(key, trip_info):
    logging.error("set for trip_info failed")
    
  return trip_info

# == Flickr

def get_flickr_nsid(flickr, token):
  logging.debug("Attempting to fetch Flickr NSID (check token)")

  key = repr(flickr)+":token="+token
  nsid  = memcache.get(key)
  if nsid is not None:
    return nsid

  # check token (and get nsid)
  auth = flickr.auth_checkToken(
            format='json',
            nojsoncallback="1",
         )

  try:
    auth = simplejson.loads(auth)
  except:
    logging.info("Could not parse '"+auth+"'")
    return None

  if auth.get("auth"):
    nsid = auth['auth']['user']['nsid']
    # username = auth.user.
    logging.info("Got Flickr user NSID "+nsid)

    if not memcache.add(key, nsid):
      logging.error("Memcache set for NSID failed")

    return nsid
  else:
    return None

def get_flickr_photos_by_machinetag(flickr, nsid, trip_info, page):
  key = repr(flickr)+":nsid="+nsid+":tripid="+str(trip_info["trip"]["id"])+":page="+page+":type=tag"
  logging.info("memcache key is "+key);
  photos = memcache.get(key)
  if photos:
    logging.info("memcache hit")
    return photos
    
  logging.debug("Attempting photo search by tag (no cache)")

  machine_tag = "dopplr:trip="+str(trip_info["trip"]["id"])
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
  photos = get_flickr_geototal(photos)
  photos = get_flickr_tagtotal(photos, trip_info["trip"]["id"])

  if not memcache.add(key, photos['photos']):
    logging.error("Memcache set for photos by tag failed")

  return photos['photos']

def get_flickr_photos_by_date(flickr, nsid, trip_info, page):
  key = repr(flickr)+":nsid="+nsid+":tripid="+str(trip_info["trip"]["id"])+":page="+page+":type=date"
  photos = memcache.get(key)
  if photos:
    return photos
    
  logging.debug("Attempting photo search by date (no cache)")

  # TODO right thing with times (which is...?)
  min_taken = trip_info["trip"]["startdate"].strftime("%Y-%m-%d 00:00:01")
  max_taken = trip_info["trip"]["finishdate"].strftime("%Y-%m-%d 23:59:59")

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

  photos = get_flickr_geototal(photos)
  photos = get_flickr_tagtotal(photos, trip_info["trip"]["id"])

  if not memcache.add(key, photos['photos']):
    logging.error("Memcache set for photos by date failed")

  return photos['photos']

def get_flickr_geototal(photos):
  photos['photos']['subtotal'] = 0
  photos['photos']['geototal'] = 0
  for photo in photos['photos']['photo']:
    photos['photos']['subtotal'] = photos['photos']['subtotal'] +1
    if photo['latitude'] and photo['longitude']:
      photos['photos']['geototal'] = photos['photos']['geototal']+1

  # if we want this as a string (we don't)
  # photos['photos']['geototal'] = str(photos['photos']['geototal'])

  return photos

def get_flickr_tagtotal(photos, trip_id):
  photos['photos']['tagtotal'] = 0
  for photo in photos['photos']['photo']:

    if photo['tags'].find('dopplr:trip='+str(trip_id)) > 0:
      photos['photos']['tagtotal'] = photos['photos']['tagtotal']+1
      photo['dopplr'] = True;

  if photos['photos']['tagtotal']:
    photos['photos']['totag']    = str(int(photos['photos']['subtotal'])-photos['photos']['tagtotal'])
  else:
    photos['photos']['totag']    = photos['photos']['subtotal']
  photos['photos']['tagtotal'] = str(photos['photos']['tagtotal'])

  return photos

# == utilities

def error_page(self, session, error):
  path = os.path.join(os.path.dirname(__file__), 'templates/error.html')
  self.response.out.write(template.render(path, {'error':error, 'session':session, }))

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
  
def build_stats(trip_list):
  stats = {'countries': {},
           'years':     {}, 
           'ordered':   {}, }
  
  for trip in trip_list:
    # skip if not a past trip
    if trip['status'] != "Past":
      continue
      
    # how long (simple version...)
    duration = trip['finishdate'] - trip['startdate']
    
    # build country data
    country = trip['city']['country']
    display = country
    inline  = country

    # special casing!
    if not country.find("United"): # TODO there's something wrong here...
      inline = "the "+country
      
    # more special casing! TODO hash
    if not country.find("Hong Kong"):
      display = "Hong Kong"
      inline  = "Hong Kong"
    
    # stuff info into the data structure
    if not country in stats['countries']:
      stats['countries'][country] = { 'duration': 0, 'trips': 0, 
                                      'display':display, 'inline':inline, }

    stats['countries'][country]['duration'] += duration.days
    stats['countries'][country]['trips']    += 1
    
    # build year data
    year = trip['startdate'].year
    if not year in stats['years']:
      stats['years'][year] = 0
    if year == trip['finishdate'].year:
      stats['years'][year] += duration.days
    else:
      if trip['finishdate'].year - year == 1:
        # spans a single year boundary, and is therefore Sane
        # if there's *anyone* who has a trip spanning two, they can bloody
        # well write this themselves. Otherwise...

        year_end = datetime(year, 12, 31)
        
        stats['years'][year] += (year_end-trip['startdate']).days
  
        year = trip['finishdate'].year
        year_start = datetime(year, 1, 1)
        if not year in stats['years']:
          stats['years'][year] = 0
        stats['years'][year] += (trip['finishdate']-year_start).days

    # do we want to supply full-blown cross-cut stats? maybe later...

  # order countries by trips for various things
#   countries = sorted(stats['countries'], key = lambda (k,v): (v,k))
  
  stats['ordered']['years'] = sorted(stats['years'])
  stats['ordered']['years'].reverse()
  
  stats['ordered']['countries'] = sorted(stats['countries'], lambda x, y: (stats['countries'][y]['duration'])-(stats['countries'][x]['duration']))
  
  return stats

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
                   ('/trip/(\d*)', TripPage),
                   ('/trip/(\d*)/by/(\w+)', TripPage),
                   ('/trip/(\d*)/by/(\w+)/(\d+)', TripPage),
                   ('/login/', LoginPage),
                   ('/form/', FormPage),
                   ('/ajax/photos.more', MoreJSON),
                   ('/ajax/photos.tag', TagJSON),
                   ('/ajax/photos.geotag', GeoTagJSON),
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