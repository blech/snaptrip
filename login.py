import os
import re
import sys
import logging

import simplejson

from google.appengine.api import urlfetch

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

class MainPage(webapp.RequestHandler):
  def get(self):
    url = "http://localhost:8080/" # TODO dynamic
    token = self.request.get('token')
    permanent = ""
    content = ""
    traveller_info = ""
    trips_info = ""
    
    if (token):
      response = urlfetch.fetch(
                   url = "https://www.dopplr.com/api/AuthSubSessionToken",
                   headers = {'Authorization': 'AuthSub token="'+token+'"'},
                 )
      match = re.search('Token=(.*)\n', response.content)
      if (match):
        permanent = match.group(1)

      if (permanent):
        # get traveller info
        response = urlfetch.fetch(
                     url = "https://www.dopplr.com/api/traveller_info.js",
                     headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
                   )
        traveller_info = simplejson.loads(response.content)

        # get trip info
        response = urlfetch.fetch(
                     url = "http://www.dopplr.com/api/trips_info.js",
                    headers = {'Authorization': 'AuthSub token="'+permanent+'"'},
                   )
        trips_info = simplejson.loads(response.content)
    
    template_values = {
      'url': url,
      'token': token,
      'permanent': permanent,
      'traveller': traveller_info,
      'trips': trips_info,
    }

    path = os.path.join(os.path.dirname(__file__), 'index.html')
    self.response.out.write(template.render(path, template_values))

application = webapp.WSGIApplication(
                  [('/', MainPage)],
                  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

# Class Dopplr():
#   def get(url, args):
#     response = urlfetch.fetch("https://www.dopplr.com/api/AuthSubSessionToken?token="+token)
#     return response.content

