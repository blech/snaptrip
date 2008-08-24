import os
import re
import sys
import logging

from datetime import datetime

import simplejson
from utilities import sessions

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

class LoginPage(webapp.RequestHandler):
  def get(self):
    url = "http://localhost:8080/login/" # TODO dynamic
    token = self.request.get('token')
    
    session = sessions.Session()
    
    permanent = ""
    if 'dopplr' in session:
        self.redirect("/")
    else:
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

    template_values = {
      'url': url,
    }
    
    path = os.path.join(os.path.dirname(__file__), 'login.html')
    self.response.out.write(template.render(path, template_values))
    
# ==

def prettify_trips(trips_info):
  logging.info("in prettify_trips")
  logging.info(trips_info)
  
  for trip in trips_info["trip"]:
    start  = datetime.strptime(trip["start"],  "%Y-%m-%d")
    finish = datetime.strptime(trip["finish"], "%Y-%m-%d")

    if start.month == finish.month and start.year == finish.year:
      trip["duration"] = start.strftime("in %B %Y");

    if start.year != finish.year:
      trip["duration"] = start.strftime("from %B %Y")+finish.strftime(" to %B %Y");

    if start.month != finish.month and start.year == finish.year:
      trip["duration"] = start.strftime("from %B ")+finish.strftime("to %B %Y");
      
    try:
      logging.info("Got pretty trip duration '"+trip["duration"]+"'")
    except KeyError:
      logging.warn("No trip duration found")
  
  return trips_info

# ==

application = webapp.WSGIApplication(
                  [('/', IndexPage),
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

