// ==UserScript==
// @name           Show Dopplr Trip Links
// @namespace      http://snaptrip.appspot.com/
// @description    Use Dopplr machine tags to show a link on Flickr photos
// @include        http://*flickr.com/photos/*/*
// @exclude        http://*flickr.com/photos/organize*
// ==/UserScript==

// Version 1.00
// Copyright (c) Paul Mison
// GPL licenced: http://www.gnu.org/copyleft/gpl.html

// Note that as well as trip IDs you'll need either dopplr:woeid or 
// woe:id machine tags to get a location in the link.

// --------------------------------------------------------------------
//
// This is a Greasemonkey user script. It requires Firefox or similar.
//
// To install, you need Greasemonkey: http://greasemonkey.mozdev.org/
// Then restart Firefox and revisit this script.
// Under Tools, there will be a new menu item to "Install User Script".
// Accept the default configuration and install.
//
// --------------------------------------------------------------------

var api_key    = "58b056f621f6476ebf144f9f72a4d05c"
var flickr_url = "http://api.flickr.com/services/rest/?method=flickr.places.resolvePlaceId&api_key="+api_key+"&format=json&nojsoncallback=1&"

display = function display() {
  var placename = "on Dopplr";

  if (display.arguments.length > 0) {
    responseDetails = display.arguments[0];
    json = eval('('+responseDetails.responseText+')');
    if (json.location.locality._content) {
      placename = "to "+json.location.locality._content;
    } else if (json.location.county._content) {
      placename = "to "+json.location.county._content;
    }
  }

  var html =  '<br/><a href="http://dopplr.com/trip/id/'+this.number+'">';
  html += '<img align="left" alt="Taken during a Dopplr trip" src="http://husk.org/misc/dopplr.png"/>';
  html += '</a> Taken during a ';
  html += '<a class="Plain" href="http://dopplr.com/trip/id/'+this.number+'">trip '+placename+'</a>.<br/>';

  var privacy = document.evaluate(
                   "//p[@class='Privacy']",
                   document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
  privacy.innerHTML += html;
}     

function find_in_list(links, regex) {
  this.match = false;
  for(var i = 0; i < links.length; i++) {  
    link = links[i];
    matches = link.href.match(regex);
    if (matches) {
      this.match = matches[1]
      break;
    }
  }

  return this.match;
}

// main
// console.log("running Dopplr trip ID finder");

var machinetags = document.getElementById('themachinetags')
var links = machinetags.getElementsByTagName('a');

if (links.length > 0) {
  // first find trip id: we can use this without a location if necessary
  this.number = find_in_list(links, 'dopplr%3Atrip%3D(\\d+)');

  // get location. This woeid should be the same as the one in dopplr.
  this.woeid = find_in_list(links, 'dopplr%3Awoeid%3D(\\d+)');
  if (!this.woeid) {
    this.woeid = find_in_list(links, 'woe%3Aid%3D(\\d+)');
  }
  
  // get name of location
  if (this.woeid) {
    GM_xmlhttpRequest({ method: 'GET',
                        url:    flickr_url + 'place_id='+this.woeid,
                        onload: display,
                     });
  } else {
    display();
  }
}
