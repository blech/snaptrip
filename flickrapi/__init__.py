#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''A FlickrAPI interface.

See `the FlickrAPI homepage`_ for more info.

.. _`the FlickrAPI homepage`: http://flickrapi.sf.net/
'''

__version__ = '1.1'
__all__ = ('FlickrAPI', 'IllegalArgumentException', 'FlickrError',
        'XMLNode', 'set_log_level', '__version__')
__author__ = u'Sybren St\u00fcvel'.encode('utf-8')

# Copyright (c) 2007 by the respective coders, see
# http://flickrapi.sf.net/
#
# This code is subject to the Python licence, as can be read on
# http://www.python.org/download/releases/2.5.2/license/
#
# For those without an internet connection, here is a summary. When this
# summary clashes with the Python licence, the latter will be applied.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import sys
import md5
import urllib
#import urllib2
import mimetools
import os.path
import logging
import copy
#import webbrowser

from google.appengine.api import urlfetch

from flickrapi.tokencache import TokenCache, SimpleTokenCache
from flickrapi.xmlnode import XMLNode
from flickrapi.multipart import Part, Multipart, FilePart
from flickrapi.exceptions import IllegalArgumentException, FlickrError
from flickrapi.cache import SimpleCache
from flickrapi import reportinghttp

logging.basicConfig()
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

def make_utf8(dictionary):
    '''Encodes all Unicode strings in the dictionary to UTF-8. Converts
    all other objects to regular strings.
    
    Returns a copy of the dictionary, doesn't touch the original.
    '''
    
    result = {}

    for (key, value) in dictionary.iteritems():
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        else:
            value = str(value)
        result[key] = value
    
    return result
        
def debug(method):
    '''Method decorator for debugging method calls.

    Using this automatically sets the log level to DEBUG.
    '''

    LOG.setLevel(logging.DEBUG)

    def debugged(*args, **kwargs):
        LOG.debug("Call: %s(%s, %s)" % (method.__name__, args,
            kwargs))
        result = method(*args, **kwargs)
        LOG.debug("\tResult: %s" % result)
        return result

    return debugged

# REST parsers, {format: parser_method, ...}. Fill by using the
# @rest_parser(format) function decorator
rest_parsers = {}

def rest_parser(format):
    '''Function decorator, use this to mark a function as the parser for REST as
    returned by Flickr.
    '''

    def decorate_parser(method):
        rest_parsers[format] = method
        return method

    return decorate_parser

class FlickrAPI:
    """Encapsulates Flickr functionality.
    
    Example usage::
      
      flickr = flickrapi.FlickrAPI(api_key)
      photos = flickr.photos_search(user_id='73509078@N00', per_page='10')
      sets = flickr.photosets_getList(user_id='73509078@N00')
    """
    
    flickr_host = "api.flickr.com"
    flickr_rest_form = "/services/rest/"
    flickr_auth_form = "/services/auth/"
    flickr_upload_form = "/services/upload/"
    flickr_replace_form = "/services/replace/"

    def __init__(self, api_key, secret=None, fail_on_error=None, username=None,
            token=None, format='xmlnode', store_token=True, cache=False):
        """Construct a new FlickrAPI instance for a given API key
        and secret.
        
        api_key
            The API key as obtained from Flickr.
        
        secret
            The secret belonging to the API key.
        
        fail_on_error
            If False, errors won't be checked by the FlickrAPI module.
            Deprecated, don't use this parameter, just handle the FlickrError
            exceptions.
        
        username
            Used to identify the appropriate authentication token for a
            certain user.
        
        token
            If you already have an authentication token, you can give
            it here. It won't be stored on disk by the FlickrAPI instance.

        format
            The response format. Use either "xmlnode" or "etree" to get a parsed
            response, or use any response format supported by Flickr to get an
            unparsed response from method calls. It's also possible to pass the
            ``format`` parameter on individual calls.

        store_token
            Disables the on-disk token cache if set to False (default is True).
            Use this to ensure that tokens aren't read nor written to disk, for
            example in web applications that store tokens in cookies.

        cache
            Enables in-memory caching of FlickrAPI calls - set to ``True`` to
            use. If you don't want to use the default settings, you can
            instantiate a cache yourself too:

            >>> f = FlickrAPI(api_key='123')
            >>> f.cache = SimpleCache(timeout=5, max_entries=100)
        """
        
        if fail_on_error is not None:
            LOG.warn("fail_on_error has been deprecated. Remove this "
                     "parameter and just handle the FlickrError exceptions.")
        else:
            fail_on_error = True

        self.api_key = api_key
        self.secret = secret
        self.fail_on_error = fail_on_error
        self.default_format = format
        
        self.__handler_cache = {}

        if token:
            # Use a memory-only token cache
            self.token_cache = SimpleTokenCache()
            self.token_cache.token = token
        elif not store_token:
            # Use an empty memory-only token cache
            self.token_cache = SimpleTokenCache()
        else:
            # Use a real token cache
            self.token_cache = TokenCache(api_key, username)

        if cache:
            self.cache = SimpleCache()
        else:
            self.cache = None

    def __repr__(self):
        '''Returns a string representation of this object.'''


        return '[FlickrAPI for key "%s"]' % self.api_key
    __str__ = __repr__

    def trait_names(self):
        '''Returns a list of method names as supported by the Flickr
        API. Used for tab completion in IPython.
        '''

        rsp = self.reflection_getMethods(format='etree')

        def tr(name):
            '''Translates Flickr names to something that can be called
            here.

            >>> tr(u'flickr.photos.getInfo')
            u'photos_getInfo'
            '''
            
            return name[7:].replace('.', '_')

        return [tr(m.text) for m in rsp.getiterator('method')]

    @rest_parser('xmlnode')
    def parse_xmlnode(self, rest_xml):
        '''Parses a REST XML response from Flickr into an XMLNode object.'''

        rsp = XMLNode.parse(rest_xml, store_xml=True)
        if rsp['stat'] == 'ok' or not self.fail_on_error:
            return rsp
        
        err = rsp.err[0]
        raise FlickrError(u'Error: %(code)s: %(msg)s' % err)

    @rest_parser('etree')
    def parse_etree(self, rest_xml):
        '''Parses a REST XML response from Flickr into an ElementTree object.'''

        # Only import it here, to maintain Python 2.4 compatibility
        import xml.etree.ElementTree

        rsp = xml.etree.ElementTree.fromstring(rest_xml)
        if rsp.attrib['stat'] == 'ok' or not self.fail_on_error:
            return rsp
        
        err = rsp.find('err')
        raise FlickrError(u'Error: %s: %s' % (
            err.attrib['code'], err.attrib['msg']))

    def sign(self, dictionary):
        """Calculate the flickr signature for a set of params.
        
        data
            a hash of all the params and values to be hashed, e.g.
            ``{"api_key":"AAAA", "auth_token":"TTTT", "key":
            u"value".encode('utf-8')}``

        """

        data = [self.secret]
        for key in sorted(dictionary.keys()):
            data.append(key)
            datum = dictionary[key]
            if isinstance(datum, unicode):
                raise IllegalArgumentException("No Unicode allowed, "
                        "argument %s (%r) should have been UTF-8 by now"
                        % (key, datum))
            data.append(datum)
        
        md5_hash = md5.new()
        md5_hash.update(''.join(data))
        return md5_hash.hexdigest()

    def encode_and_sign(self, dictionary):
        '''URL encodes the data in the dictionary, and signs it using the
        given secret, if a secret was given.
        '''
        
        dictionary = make_utf8(dictionary)
        if self.secret:
            dictionary['api_sig'] = self.sign(dictionary)
        return urllib.urlencode(dictionary)
        
    def __getattr__(self, attrib):
        """Handle all the regular Flickr API calls.
        
        Example::

            flickr.auth_getFrob(api_key="AAAAAA")
            xmlnode = flickr.photos_getInfo(photo_id='1234')
            xmlnode = flickr.photos_getInfo(photo_id='1234', format='xmlnode')
            json = flickr.photos_getInfo(photo_id='1234', format='json')
            etree = flickr.photos_getInfo(photo_id='1234', format='etree')
        """

        # Refuse to act as a proxy for unimplemented special methods
        if attrib.startswith('_'):
            raise AttributeError("No such attribute '%s'" % attrib)

        # Construct the method name and see if it's cached
        method = "flickr." + attrib.replace("_", ".")
        if method in self.__handler_cache:
            return self.__handler_cache[method]
        
        def handler(**args):
            '''Dynamically created handler for a Flickr API call'''

            if self.token_cache.token and not self.secret:
                raise ValueError("Auth tokens cannot be used without "
                                 "API secret")

            # Set some defaults
            defaults = {'method': method,
                        'auth_token': self.token_cache.token,
                        'api_key': self.api_key,
                        'format': self.default_format}

            args = self.__supply_defaults(args, defaults)

            return self.__wrap_in_parser(self.__flickr_call,
                    parse_format=args['format'], **args)

        handler.method = method
        self.__handler_cache[method] = handler
        return handler
    
    def __supply_defaults(self, args, defaults):
        '''Returns a new dictionary containing ``args``, augmented with defaults
        from ``defaults``.

        Defaults can be overridden, or completely removed by setting the
        appropriate value in ``args`` to ``None``.

        >>> f = FlickrAPI('123')
        >>> f._FlickrAPI__supply_defaults(
        ...  {'foo': 'bar', 'baz': None, 'token': None},
        ...  {'baz': 'foobar', 'room': 'door'})
        {'foo': 'bar', 'room': 'door'}
        '''

        result = args.copy()
        for key, default_value in defaults.iteritems():
            # Set the default if the parameter wasn't passed
            if key not in args:
                result[key] = default_value

        for key, value in result.copy().iteritems():
            # You are able to remove a default by assigning None, and we can't
            # pass None to Flickr anyway.
            if result[key] is None:
                del result[key]
        
        return result

    def __flickr_call(self, **kwargs):
        '''Performs a Flickr API call with the given arguments. The method name
        itself should be passed as the 'method' parameter.
        
        Returns the unparsed data from Flickr::

            data = self.__flickr_call(method='flickr.photos.getInfo',
                photo_id='123', format='rest')
        '''

        LOG.debug("Calling %s" % kwargs)

        post_data = self.encode_and_sign(kwargs)

        # Return value from cache if available
        if self.cache and self.cache.get(post_data):
            return self.cache.get(post_data)

        url = "http://" + FlickrAPI.flickr_host + FlickrAPI.flickr_rest_form
#         flicksocket = urllib.urlopen(url, post_data)
#         reply = flicksocket.read()
#         flicksocket.close()

        result = urlfetch.fetch(url, post_data, "POST")
        reply  = result.content

        # Store in cache, if we have one
        if self.cache is not None:
            self.cache.set(post_data, reply)

        return reply
    
    def __wrap_in_parser(self, wrapped_method, parse_format, *args, **kwargs):
        '''Wraps a method call in a parser.

        The parser will be looked up by the ``parse_format`` specifier. If there
        is a parser and ``kwargs['format']`` is set, it's set to ``rest``, and
        the response of the method is parsed before it's returned.
        '''

        # Find the parser, and set the format to rest if we're supposed to
        # parse it.
        if parse_format in rest_parsers and 'format' in kwargs:
            kwargs['format'] = 'rest'

        LOG.debug('Wrapping call %s(self, %s, %s)' % (wrapped_method, args,
            kwargs))
        data = wrapped_method(*args, **kwargs)

        # Just return if we have no parser
        if parse_format not in rest_parsers:
            return data

        # Return the parsed data
        parser = rest_parsers[parse_format]
        return parser(self, data)

    def auth_url(self, perms, frob):
        """Return the authorization URL to get a token.

        This is the URL the app will launch a browser toward if it
        needs a new token.
            
        perms
            "read", "write", or "delete"
        frob
            picked up from an earlier call to FlickrAPI.auth_getFrob()

        """

        encoded = self.encode_and_sign({
                    "api_key": self.api_key,
                    "frob": frob,
                    "perms": perms})

        return "http://%s%s?%s" % (FlickrAPI.flickr_host, \
            FlickrAPI.flickr_auth_form, encoded)

    def web_login_url(self, perms):
        '''Returns the web login URL to forward web users to.

        perms
            "read", "write", or "delete"
        '''
        
        encoded = self.encode_and_sign({
                    "api_key": self.api_key,
                    "perms": perms})

        return "http://%s%s?%s" % (FlickrAPI.flickr_host, \
            FlickrAPI.flickr_auth_form, encoded)

    def upload(self, filename, callback=None, **arg):
        """Upload a file to flickr.

        Be extra careful you spell the parameters correctly, or you will
        get a rather cryptic "Invalid Signature" error on the upload!

        Supported parameters:

        filename
            name of a file to upload
        callback
            method that gets progress reports
        title
            title of the photo
        description
            description a.k.a. caption of the photo
        tags
            space-delimited list of tags, ``'''tag1 tag2 "long
            tag"'''``
        is_public
            "1" or "0" for a public resp. private photo
        is_friend
            "1" or "0" whether friends can see the photo while it's
            marked as private
        is_family
            "1" or "0" whether family can see the photo while it's
            marked as private

        The callback method should take two parameters:
        def callback(progress, done)
        
        Progress is a number between 0 and 100, and done is a boolean
        that's true only when the upload is done.
        
        For now, the callback gets a 'done' twice, once for the HTTP
        headers, once for the body.
        """

        if not filename:
            raise IllegalArgumentException("filename must be specified")
        
        # verify key names
        required_params = ('api_key', 'auth_token', 'api_sig')
        optional_params = ('title', 'description', 'tags', 'is_public', 
                           'is_friend', 'is_family')
        possible_args = required_params + optional_params
        
        for a in arg.keys():
            if a not in possible_args:
                raise IllegalArgumentException("Unknown parameter "
                        "'%s' sent to FlickrAPI.upload" % a)

        arguments = {'auth_token': self.token_cache.token,
                     'api_key': self.api_key}
        arguments.update(arg)

        # Convert to UTF-8 if an argument is an Unicode string
        arg = make_utf8(arguments)
        
        if self.secret:
            arg["api_sig"] = self.sign(arg)
        url = "http://" + FlickrAPI.flickr_host + FlickrAPI.flickr_upload_form

        # construct POST data
        body = Multipart()

        for a in required_params + optional_params:
            if a not in arg:
                continue
            
            part = Part({'name': a}, arg[a])
            body.attach(part)

        filepart = FilePart({'name': 'photo'}, filename, 'image/jpeg')
        body.attach(filepart)

        return self.__send_multipart(url, body, callback)
    
    def replace(self, filename, photo_id):
        """Replace an existing photo.

        Supported parameters:

        filename
            name of a file to upload
        photo_id
            the ID of the photo to replace
        """
        
        if not filename:
            raise IllegalArgumentException("filename must be specified")
        if not photo_id:
            raise IllegalArgumentException("photo_id must be specified")

        args = {'filename': filename,
                'photo_id': photo_id,
                'auth_token': self.token_cache.token,
                'api_key': self.api_key}

        args = make_utf8(args)
        
        if self.secret:
            args["api_sig"] = self.sign(args)
        url = "http://" + FlickrAPI.flickr_host + FlickrAPI.flickr_replace_form

        # construct POST data
        body = Multipart()

        for arg, value in args.iteritems():
            # No part for the filename
            if value == 'filename':
                continue
            
            part = Part({'name': arg}, value)
            body.attach(part)

        filepart = FilePart({'name': 'photo'}, filename, 'image/jpeg')
        body.attach(filepart)

        return self.__send_multipart(url, body)

    def __send_multipart(self, url, body, progress_callback=None):
        '''Sends a Multipart object to an URL.
        
        Returns the resulting XML from Flickr.
        '''

        LOG.debug("Uploading to %s" % url)
        request = urllib2.Request(url)
        request.add_data(str(body))
        
        (header, value) = body.header()
        request.add_header(header, value)
        
        if progress_callback:
            response = reportinghttp.urlopen(request, progress_callback)
        else:
            response = urllib2.urlopen(request)
        rspXML = response.read()

        return self.parse_xmlnode(rspXML)

    @classmethod
    def test_failure(cls, rsp, exception_on_error=True):
        """Exit app if the rsp XMLNode indicates failure."""

        LOG.warn("FlickrAPI.test_failure has been deprecated and will be "
                 "removed in FlickrAPI version 1.2.")

        if rsp['stat'] != "fail":
            return
        
        message = cls.get_printable_error(rsp)
        LOG.error(message)
        
        if exception_on_error:
            raise FlickrError(message)

    @classmethod
    def get_printable_error(cls, rsp):
        """Return a printed error message string of an XMLNode Flickr response."""

        LOG.warn("FlickrAPI.get_printable_error has been deprecated "
                 "and will be removed in FlickrAPI version 1.2.")

        return "%s: error %s: %s" % (rsp.name, \
            cls.get_rsp_error_code(rsp), cls.get_rsp_error_msg(rsp))

    @classmethod
    def get_rsp_error_code(cls, rsp):
        """Return the error code of an XMLNode Flickr response, or 0 if no
        error.
        """

        LOG.warn("FlickrAPI.get_rsp_error_code has been deprecated and will be "
                 "removed in FlickrAPI version 1.2.")

        if rsp['stat'] == "fail":
            return int(rsp.err[0]['code'])

        return 0

    @classmethod
    def get_rsp_error_msg(cls, rsp):
        """Return the error message of an XMLNode Flickr response, or "Success"
        if no error.
        """

        LOG.warn("FlickrAPI.get_rsp_error_msg has been deprecated and will be "
                 "removed in FlickrAPI version 1.2.")

        if rsp['stat'] == "fail":
            return rsp.err[0]['msg']

        return "Success"

    def validate_frob(self, frob, perms):
        '''Lets the user validate the frob by launching a browser to
        the Flickr website.
        '''
        
        auth_url = self.auth_url(perms, frob)
        webbrowser.open(auth_url, True, True)
        
    def get_token_part_one(self, perms="read"):
        """Get a token either from the cache, or make a new one from
        the frob.
        
        This first attempts to find a token in the user's token cache
        on disk. If that token is present and valid, it is returned by
        the method.
        
        If that fails (or if the token is no longer valid based on
        flickr.auth.checkToken) a new frob is acquired.  The frob is
        validated by having the user log into flickr (with a browser).
        
        To get a proper token, follow these steps:
            - Store the result value of this method call
            - Give the user a way to signal the program that he/she
              has authorized it, for example show a button that can be
              pressed.
            - Wait for the user to signal the program that the
              authorization was performed, but only if there was no
              cached token.
            - Call flickrapi.get_token_part_two(...) and pass it the
              result value you stored.
        
        The newly minted token is then cached locally for the next
        run.
        
        perms
            "read", "write", or "delete"           
        
        An example::
        
            (token, frob) = flickr.get_token_part_one(perms='write')
            if not token: raw_input("Press ENTER after you authorized this program")
            flickr.get_token_part_two((token, frob))
        """
        
        # see if we have a saved token
        token = self.token_cache.token
        frob = None

        # see if it's valid
        if token:
            LOG.debug("Trying cached token '%s'" % token)
            try:
                rsp = self.auth_checkToken(auth_token=token, format='xmlnode')

                # see if we have enough permissions
                tokenPerms = rsp.auth[0].perms[0].text
                if tokenPerms == "read" and perms != "read": token = None
                elif tokenPerms == "write" and perms == "delete": token = None
            except FlickrError:
                LOG.debug("Cached token invalid")
                self.token_cache.forget()
                token = None

        # get a new token if we need one
        if not token:
            # get the frob
            LOG.debug("Getting frob for new token")
            rsp = self.auth_getFrob(auth_token=None, format='xmlnode')
            self.test_failure(rsp)

            frob = rsp.frob[0].text

            # validate online
            self.validate_frob(frob, perms)

        return (token, frob)
        
    def get_token_part_two(self, (token, frob)):
        """Part two of getting a token, see ``get_token_part_one(...)`` for details."""

        # If a valid token was obtained in the past, we're done
        if token:
            LOG.debug("get_token_part_two: no need, token already there")
            self.token_cache.token = token
            return token
        
        LOG.debug("get_token_part_two: getting a new token for frob '%s'" % frob)

        return self.get_token(frob)
    
    def get_token(self, frob):
        '''Gets the token given a certain frob. Used by ``get_token_part_two`` and
        by the web authentication method.
        '''
        
        # get a token
        rsp = self.auth_getToken(frob=frob, auth_token=None, format='xmlnode')
        self.test_failure(rsp)

        token = rsp.auth[0].token[0].text
        LOG.debug("get_token: new token '%s'" % token)
        
        # store the auth info for next time
        self.token_cache.token = token

        return token

def set_log_level(level):
    '''Sets the log level of the logger used by the FlickrAPI module.
    
    >>> import flickrapi
    >>> import logging
    >>> flickrapi.set_log_level(logging.INFO)
    '''
    
    import flickrapi.tokencache

    LOG.setLevel(level)
    flickrapi.tokencache.LOG.setLevel(level)


if __name__ == "__main__":
    print "Running doctests"
    import doctest
    doctest.testmod()
    print "Tests OK"
