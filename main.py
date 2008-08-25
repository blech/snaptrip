import os
import re
import md5
import sys
import logging

from datetime import datetime

import simplejson
from utilities import sessions

# flickr
import flickrapi
flickr = flickrapi.FlickrAPI('d0f74bf817f518ae4ce7892ac7fce7de', 
                             '312fb375d41fcb09',
                             store_token=False, )

# gae
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
      # trips_info = prettify_trips(trips_info)
    except ValueError:
      logging.warn("Didn't get a JSON response from traveller_info")
    
    template_values = {
      'session': session,
      'permanent': permanent,
      'traveller': traveller_info,
      'trips': trips_info,
    }

    path = os.path.join(os.path.dirname(__file__), 'index.html')
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

    url = "https://www.dopplr.com/api/trip_info.js?trip_id="+trip_id+"&token=929635a320b1a2b4af26a28262f9b4df"
    response = urlfetch.fetch(
                 url = url,
                 headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
               )
    trip_info = {}
    logging.info(response.content)
    try:
      trip_info = simplejson.loads(response.content)
    except ValueError:
      logging.warn("Didn't get a JSON response from trip_info")
    
    template_values = {
      'session': session,
      'permanent': permanent,
      'trip': trip_info,
    }

    path = os.path.join(os.path.dirname(__file__), 'trip.html')
    self.response.out.write(template.render(path, template_values))    

class LoginPage(webapp.RequestHandler):
  def get(self):
    callback_url = "http://localhost:8080/login/" 
  
    dopplr_url = "https://www.dopplr.com/api/AuthSubRequest?scope=http://www.dopplr.com&next="+callback_url+"&session=1"
    dopplr_token = self.request.get('token')

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
        session['flickr'] = permanent
        self.redirect("/")

    template_values = {
      'dopplr_url': dopplr_url,
      'flickr_url': flickr_url,
      'error':      error,
      'frob':       frob,
      'permanent':  permanent,
      'session':    session,
    }
    
    path = os.path.join(os.path.dirname(__file__), 'login.html')
    self.response.out.write(template.render(path, template_values))
    
# ==

def prettify_trips(trips_info):
  logging.info("in prettify_trips")
  logging.info(trips_info)
  
  for trip in trips_info["trip"]:
    trip["startdate"]  = datetime.strptime(trip["start"],  "%Y-%m-%d")
    trip["finishdate"] = datetime.strptime(trip["finish"], "%Y-%m-%d")
  return trips_info

# ==

application = webapp.WSGIApplication(
                  [('/', IndexPage),
                   ('/trip/(\d+)', TripPage),
                   ('/login/', LoginPage)],
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

