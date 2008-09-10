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

from google.appengine.api import urlfetch

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

# jinja2
env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/')))

class IndexPage(webapp.RequestHandler):
  def get(self, who=""):
    permanent = ''
    session = sessions.Session()
    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    traveller_info = get_traveller_info(permanent, who)
    trips_info     = get_trip_info(permanent, who)

    stats      = {}
    if trips_info:
      stats = build_stats(trips_info)
    
    template_values = {
      'session': session,
      'permanent': permanent,
      'traveller': traveller_info['traveller'],
      'trips': trips_info['trip'],
      'stats': stats,
    }
    
    path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
    template = env.get_template('index.html')
    
    self.response.out.write(template.render(template_values))

class TripPage(webapp.RequestHandler):
  def get(self, trip_id):
    permanent = ''
    session = sessions.Session()

    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    if not trip_id:
      return self.redirect("/")

    url = "https://www.dopplr.com/api/trip_info.js?trip_id="+trip_id
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
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

    start  = datetime.strptime(trip_info["trip"]["start"],  "%Y-%m-%d")
    trip_info["trip"]["startdate"]  = start
    
    finish = datetime.strptime(trip_info["trip"]["finish"], "%Y-%m-%d")
    trip_info["trip"]["finishdate"] = finish

    # do Flickr photo search
    token = ""
    nsid  = ""
    try:
      token = session['flickr']
    except KeyError:
      logging.warn("No Flickr token")

    if token: # disable photos
      # get keys
      keys = get_keys(self.request.host)
      flickr = get_flickr(keys, token)      
  
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

    if nsid:
      min_taken = start.strftime("%Y-%m-%d 00:00:01")
      max_taken = finish.strftime("%Y-%m-%d 23:59:59")
    
      # TODO user ID
      # TODO dtrt with day ends
      photos = flickr.photos_search(
                 token=token,
                 format='json',
                 nojsoncallback="1",
                 user_id=nsid,
                 min_taken_date=min_taken,
                 max_taken_date=max_taken,
                 sort="date-taken-asc",
                 per_page="24",
                 extras='license, date_upload, date_taken, tags, o_dims, views, media',
               )
      photos = simplejson.loads(photos)
      photos = photos['photos']
      url = ""
    else:
      photos = ""
      keys = get_keys(self.request.host)
      flickr = get_flickr(keys)      
      url = flickr.web_login_url('write')
      # if (permanent):
      #   url = "" # TODO reflect in template
    
    template_values = {
      'session':    session,
      'permanent':  permanent,
      'trip':       trip_info,
      'photos':     photos,
      'url':        url,
      'keys':       keys,
    }

    path = os.path.join(os.path.dirname(__file__), 'templates/trip.html')
    self.response.out.write(template.render(path, template_values))    

class LoginPage(webapp.RequestHandler):
  def get(self):
    callback_url = "http://"+self.request.host+"/login/" 
  
    dopplr_url = "https://www.dopplr.com/api/AuthSubRequest?scope=http://www.dopplr.com&next="+callback_url+"&session=1"
    dopplr_token = self.request.get('token')

    keys = get_keys(self.request.host)
    flickr = get_flickr(keys)
    flickr_url = flickr.web_login_url('write')
    
    session = sessions.Session()
    
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
        session['name'] = dopplr_info['traveller']['name']        
        session['nick'] = dopplr_info['traveller']['nick']        

        self.redirect("/")

    
    if frob:
      permanent = flickr.get_token(frob)
      if permanent:
        # TODO user ID
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
  except ValueError:
    logging.warn("Didn't get a JSON response from traveller_info")

  return traveller_info

def get_trip_info(token, who=""):
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
    # trips_info = prettify_trips(trips_info)
  except ValueError:
    logging.warn("Didn't get a JSON response from traveller_info")

  if trips_info:
       prettify_trips(trips_info)

  return trips_info

# == utilities

def prettify_trips(trip_list):
  # parse dates to datetime objects
  now = datetime.now()
  
  for trip in trip_list["trip"]:
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
  
  for trip in trip_list["trip"]:
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

def get_flickr(keys, token=''):
  flickr = flickrapi.FlickrAPI(keys['flickr_key'], keys['flickr_sec'], 
                               token=token, store_token=False, cache=True)
  flickr.cache = flickrapi.SimpleCache(timeout=300, max_entries=200)

  return flickr


# ==

application = webapp.WSGIApplication(
                  [('/', IndexPage),
                   ('/where/(\w*)', IndexPage),
                   ('/trip/(\d*)', TripPage),
                   ('/login/', LoginPage)
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