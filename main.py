import os
import re
import md5
import sys
import logging

from datetime import datetime

import simplejson
from utilities import sessions

import flickrapi

from google.appengine.api import urlfetch

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

class IndexPage(webapp.RequestHandler):
  def get(self):
    permanent = ''
    session = sessions.Session()
    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    who = ""; # TODO grab from URL

    # get traveller info (todo cache?)
    url = "https://www.dopplr.com/api/traveller_info.js"
    if who:
      url += "?traveller="+who
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
               )
    traveller_info = {}
    try:
      traveller_info = simplejson.loads(response.content)
    except ValueError:
      logging.warn("Didn't get a JSON response from traveller_info")

    # get trip info
    url = "https://www.dopplr.com/api/trips_info.js"
    if who:
      url += "?traveller="+who
    response = urlfetch.fetch(
                 url = url,
                headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
               )
    trips_info = {}
    try:
      trips_info = simplejson.loads(response.content)
      prettify_trips(trips_info)
      stats = build_stats(trips_info)
      # trips_info = prettify_trips(trips_info)
    except ValueError:
      logging.warn("Didn't get a JSON response from traveller_info")
    
    template_values = {
      'session': session,
      'permanent': permanent,
      'traveller': traveller_info['traveller'],
      'trips': trips_info['trip'],
      'stats': stats,
    }

    path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
    self.response.out.write(template.render(path, template_values))

class TripPage(webapp.RequestHandler):
  def get(self, trip_id):
    permanent = ''
    session = sessions.Session()

    try:
      permanent = session['dopplr']
    except KeyError, e:
      return self.redirect("/login/")

    logging.warn("Got trip_id "+trip_id)

    # get keys
    keys = get_keys(self.request.host)
    flickr = get_flickr(keys)      

    if not trip_id:
      return self.redirect("/")

    url = "https://www.dopplr.com/api/trip_info.js?trip_id="+trip_id
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
               )
    trip_info = {}
    try:
#       logging.info(response.content)
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
      # check token (and get nsid)
      logging.warn("Using Flickr token "+token)

      try:
        auth = flickr.auth_checkToken(
                  token=token,
                  format='json',
                  nojsoncallback="1",
               )
        logging.info(auth)
        # username = auth.user.
        auth = simplejson.loads(auth)
        logging.info(auth)
        if auth.get("auth"):
          nsid = auth['auth']['user']['nsid']
          logging.info(nsid)

      except flickrapi.FlickrError:
        token = ""

    if nsid:
      min_taken = start.strftime("%Y-%m-%d 00:00:01")
      max_taken = finish.strftime("%Y-%m-%d 23:59:59")
    
      logging.info("Time duration: "+min_taken+" to "+max_taken)
    
      # TODO user ID
      # TODO dtrt with day ends
      photos = flickr.photos_search(
                 token=token,
                 format='json',
                 nojsoncallback="1",
                 user_id='48600109393@N01',
                 min_taken_date=min_taken,
                 max_taken_date=max_taken,
                 sort="date-taken-asc",
                 per_page="24",
                 extras='license, date_upload, date_taken, tags, o_dims, views, media',
               )
      logging.info(photos)
      photos = simplejson.loads(photos)
      photos = photos['photos']
      url = ""
    else:
      photos = ""
      url = flickr.web_login_url('write')
    
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
        session['dopplr'] = permanent
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
    


# ==

def prettify_trips(trip_list):
  # parse dates to datetime objects
  for trip in trip_list["trip"]:
    trip["startdate"]  = datetime.strptime(trip["start"],  "%Y-%m-%d")
    trip["finishdate"] = datetime.strptime(trip["finish"], "%Y-%m-%d")
  return trip_list
  
def build_stats(trip_list):
  stats = {'countries': {},
           'year':      {}, }
  
  for trip in trip_list["trip"]:
    # how long?
    duration = trip['finishdate'] - trip['startdate']
    
    # countries
    country = trip['city']['country']
    if not country in stats['countries']:
      logging.info("reset "+country)
      stats['countries'][country] = { 'duration': 0, 'trips': 0, }
      
    stats['countries'][country]['duration'] += duration.days
    stats['countries'][country]['trips']    += 1
    
  return stats

def get_keys(host):
  # get the right API keys for the current server
  logging.info("Got host "+host)
  keys = {}

  if host.find("appspot.com"):
    keys = {
      'gmap':       "ABQIAAAAAuD6u2ORBgn25rPuxX1qxxQ4d34u_oYfzC9kAIhtljFln5QgnBSLj4qbVLSLA2cKssBO11cTRrUoXg",
      'flickr_key': "6e990ae1ba4697e88afa5d626b138fd2",
      'flickr_sec': "172d6389fecab4bd",
    }
    
  if host.find("localhost"):
    keys = {
      'gmap':       "ABQIAAAAAuD6u2ORBgn25rPuxX1qxxTwM0brOpm-All5BF6PoaKBxRWWERQtnsYZp4mF-8WXCriNCoSun02Skw",
      'flickr_key': "d0f74bf817f518ae4ce7892ac7fce7de",
      'flickr_sec': "312fb375d41fcb09",
    }
    
  return keys

def get_flickr(keys):
  flickr = flickrapi.FlickrAPI(keys['flickr_key'], keys['flickr_sec'], 
                               store_token=False, cache=True)
  flickr.cache = flickrapi.SimpleCache(timeout=300, max_entries=200)

  return flickr

# ==

application = webapp.WSGIApplication(
                  [('/', IndexPage),
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