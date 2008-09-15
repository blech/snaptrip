import os
import re
import md5
import sys
import logging

from datetime import datetime
from operator import itemgetter

import simplejson
from utilities import sessions
from jinja2 import FileSystemLoader, Environment

import flickrapi

from google.appengine.api import mail
from google.appengine.api import urlfetch

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

# jinja2
env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/')))

class IndexPage(webapp.RequestHandler):
  def get(self, who=""):
    permanent = ''
    session = get_session()
    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    stats           = {}
    trips_info      = get_trips_info(permanent, who)
    if trips_info:
      stats         = build_stats(trips_info)
    
    template_values = {
      'session':    session,
      'permanent':  permanent,
      'traveller':  get_traveller_info(permanent, who),
      'trips':      trips_info,
      'stats':      stats,
    }
    
    path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
    template = env.get_template('index.html')
    
    self.response.out.write(template.render(template_values))

class TripPage(webapp.RequestHandler):
  def get(self, trip_id):
    permanent = ''
    session = get_session()

    # get trip id and hence info from Dopplr
    if not trip_id:
      return self.redirect("/")

    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    trip_info = get_trip_info(permanent, trip_id)

    # initialise template data before we call Flickr
    template_values = {
      'session':    session,
      'trip':       trip_info,
      'keys':       get_keys(self.request.host),
    }

    token = ''
    try:
      token = session['flickr']
    except KeyError:
      logging.warn("No Flickr token")
  
    if session["nick"] == trip_info["trip"]["nick"]:
      if token and not trip_info["trip"]["status"] == "Future":
        # get keys
        keys = get_keys(self.request.host)
        flickr = get_flickr(keys, token)      
  
        photos = get_flickr_photos_by_machinetag(flickr, trip_info)
        if photos and photos['total']:
          template_values['photos'] = photos
          template_values['method'] = "machinetag"
        else:
          template_values['photos'] = get_flickr_photos_by_date(flickr, trip_info)
          template_values['method'] = "date"

      else:
        template_values['url'] = get_flickr_auth_url(self.request.host);

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
    
    error = ""
    permanent = ""
    token = self.request.get('token') # from Dopplr
    frob  = self.request.get('frob')  # from Flickr

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
 
        session['dopplr'] = permanent
        session['name'] = dopplr_info['name']        
        session['nick'] = dopplr_info['nick']        

        self.redirect("/")

    
    if frob:
      permanent = flickr.get_token(frob)
      if permanent:
        session['flickr'] = permanent
        self.redirect("/")

    template_values = {
      'dopplr_url': dopplr_url,
      'flickr_url': flickr_url,
      'error':      error,
      'frob':       frob,
      'permanent':  permanent,
      'session':    session,
      'keys':       keys,
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

    logging.info("Got name '"+name+"' and text '"+text+"'")

    sent = False
    error = ''

    email = ''
    if session['dopplr']:
      traveller = get_traveller_info(session['dopplr'])
      email = traveller['email']
    
    if name and text:
      sent = True;  
      # send
      message = mail.EmailMessage(subject='snaptrip feedback (via form)',)
      message.sender = "misonp+snaptrip@gmail.com"
    
      message.to = "Paul Mison <misonp+snaptrip@gmail.com>"
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
    token = self.request.get("token")
    nsid = self.request.get("nsid")
    page = self.request.get("page")

    if not token or not nsid:
      return self.response.out.write('')

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token)

    logging.info("'"+token+"', '"+nsid+"', '"+page+"'")    

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
  #                extras='license, date_upload, date_taken, tags, o_dims, views, media',
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
  #                extras='license, date_upload, date_taken, tags, o_dims, views, media',
  #                privacy_filter="1",
               )
  
      self.response.out.write(json)

class TagJSON(webapp.RequestHandler):
  def get(self):
    logging.info("in TagJSON")
    token = self.request.get("token")

    if not token:
      return self.response.out.write('')

    photo_id = self.request.get("photo_id")
    trip_id = self.request.get("trip_id")

    logging.info("Got token "+token+", photo_id "+photo_id+" and trip id '"+trip_id+"'")

    if not photo_id or not trip_id:
      logging.warn("No photo_id or trip_id!")
      return self.response.out.write('')

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys, token, True)
    logging.info(flickr.cache)

    json = flickr.photos_addTags(
               format='json',
               nojsoncallback="1",
               photo_id=photo_id,
               tags="dopplr:trip="+trip_id+" dopplr:tagged=snaptrip",
              )

    # DownloadError: ApplicationError: 3
              
    logging.info("got json "+repr(json));

    self.response.out.write(json)

# == Dopplr

def get_traveller_info(token, who=""):
  # get traveller info (todo cache?)
  url = "https://www.dopplr.com/api/traveller_info.js"
  if who:
    url += "?traveller="+who
  response = urlfetch.fetch(
               url = url,
               headers = {'Authorization': 'AuthSub token="'+token+'"'},
             )
  traveller_info = {}
  try:
    traveller_info = simplejson.loads(response.content)
    traveller_info = traveller_info['traveller']
  except ValueError:
    logging.warn("Didn't get a JSON response from traveller_info")

  return traveller_info

def get_trips_info(token, who=""):
  # get trip info
  url = "https://www.dopplr.com/api/trips_info.js"
  if who:
    url += "?traveller="+who
  response = urlfetch.fetch(
               url = url,
               headers = {'Authorization': 'AuthSub token="'+token+'"'},
             )
  trips_info = {}
  try:
    trips_info = simplejson.loads(response.content)
    trips_info = trips_info['trip']
    # trips_info = prettify_trips(trips_info)
  except ValueError:
    logging.warn("Didn't get a JSON response from traveller_info")

  if trips_info:
    prettify_trips(trips_info)

  return trips_info

def get_trip_info(token, trip_id):
  url = "https://www.dopplr.com/api/trip_info.js?trip_id="+trip_id
  response = urlfetch.fetch(
               url = url,
               headers = {'Authorization': 'AuthSub token="'+token+'"'},
             )
  trip_info = {}
  try:
    trip_info = simplejson.loads(response.content)
  except ValueError:
    logging.warn("Didn't get a JSON response from trip_info")
    
  if trip_info.get('error'):
    # not good. show to user?
    logging.error(trip_info['error'])
    return self.redirect("/")

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
    
  return trip_info

# == Flickr

def get_flickr_nsid(flickr):
  logging.debug("Attempting to fetch Flickr NSID (check token)")
  nsid  = ""

  # check token (and get nsid)
  auth = flickr.auth_checkToken(
            format='json',
            nojsoncallback="1",
         )

  auth = simplejson.loads(auth)
  if auth.get("auth"):
    nsid = auth['auth']['user']['nsid']
    # username = auth.user.
    logging.info("Got Flickr user NSID "+nsid)

  return nsid

def get_flickr_photos_by_machinetag(flickr, trip_info):
  logging.debug("Attempting photo search by date")

  nsid  = get_flickr_nsid(flickr)

  if nsid:
    machine_tag = "dopplr:trip="+str(trip_info["trip"]["id"])
    logging.info("Got trip ID to search on: "+machine_tag);
   
    photos = flickr.photos_search(
               format='json',
               nojsoncallback="1",
               user_id=nsid,
               tags=machine_tag,
               sort="date-taken-asc",
               per_page="24",
#                extras='license, date_upload, date_taken, tags, o_dims, views, media',
#                privacy_filter="1",
             )
    photos = simplejson.loads(photos)
    return photos['photos']

def get_flickr_photos_by_date(flickr, trip_info):
  logging.debug("Attempting photo search by date")
  nsid  = get_flickr_nsid(flickr)

  # TODO right thing with times
  if nsid:
    min_taken = trip_info["trip"]["startdate"].strftime("%Y-%m-%d 00:00:01")
    max_taken = trip_info["trip"]["finishdate"].strftime("%Y-%m-%d 23:59:59")
  
    # TODO dtrt with day ends
    photos = flickr.photos_search(
               format='json',
               nojsoncallback="1",
               user_id=nsid,
               min_taken_date=min_taken,
               max_taken_date=max_taken,
               sort="date-taken-asc",
               per_page="24",
#                extras='license, date_upload, date_taken, tags, o_dims, views, media',
#                privacy_filter="1",
             )
    photos = simplejson.loads(photos)
    return photos['photos']

def get_flickr_auth_url(host):
  keys = get_keys(host)
  flickr = get_flickr(keys)      
  return flickr.web_login_url('write')
    
# == utilities

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
           'ordered':   [], }
  
  for trip in trip_list:
    # skip if not a past trip
    if trip['status'] != "Past":
      continue
      
    # how long (simple version...)
    duration = trip['finishdate'] - trip['startdate']
    
    # build country data
    country = trip['city']['country']
    display = country

    # special casing!
    # if not country.find("United"):
    #   display = "the "+country
      
    # more special casing! TODO hash
    if not country.find("Hong Kong"):
      display = "Hong Kong"
    
    # stuff info into the data structure
    if not country in stats['countries']:
      stats['countries'][country] = { 'duration': 0, 'trips': 0, 'display':display,}

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
  
#   stats['ordered'] = countries

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
                   ('/login/', LoginPage),
                   ('/form/', FormPage),
                   ('/ajax/photos.more', MoreJSON),
                   ('/ajax/photos.tag', TagJSON),
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