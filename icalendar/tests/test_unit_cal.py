from . import unittest
import icalendar
from datetime import datetime, timedelta
import pytz


class TestCalComponent(unittest.TestCase):

    def test_cal_Component(self):
        from icalendar.cal import Component, Calendar, Event
        from icalendar import prop

        # A component is like a dictionary with extra methods and attributes.
        c = Component()
        c.name = 'VCALENDAR'

        # Every key defines a property.A property can consist of either a
        # single item. This can be set with a single value...
        c['prodid'] = '-//max m//icalendar.mxm.dk/'
        self.assertEqual(c,
            Calendar({'PRODID': '-//max m//icalendar.mxm.dk/'}))

        # or with a list
        c['ATTENDEE'] = ['Max M', 'Rasmussen']
        self.assertEqual(c,
            Calendar({'ATTENDEE': ['Max M', 'Rasmussen'],
                      'PRODID': '-//max m//icalendar.mxm.dk/'}))

        # if you use the add method you don't have to considder if a value is
        # a list or not.
        c = Component()
        c.name = 'VEVENT'
        c.add('attendee', 'maxm@mxm.dk')
        c.add('attendee', 'test@example.dk')
        self.assertEqual(c,
            Event({'ATTENDEE': [prop.vCalAddress('maxm@mxm.dk'),
                                prop.vCalAddress('test@example.dk')]}))

        # You can get the values back directly ...
        c.add('prodid', '-//my product//')
        self.assertEqual(c['prodid'], prop.vText(u'-//my product//'))

        # ... or decoded to a python type
        self.assertEqual(c.decoded('prodid'), '-//my product//')

        # With default values for non existing properties
        self.assertEqual(c.decoded('version', 'No Version'), 'No Version')

        c.add('rdate', [datetime(2013, 3, 28), datetime(2013, 3, 27)])
        self.assertEqual(type(c.decoded('rdate')), prop.vDDDLists)

        # The component can render itself in the RFC 2445 format.
        c = Component()
        c.name = 'VCALENDAR'
        c.add('attendee', 'Max M')
        self.assertEqual(c.to_ical(),
            'BEGIN:VCALENDAR\r\nATTENDEE:Max M\r\nEND:VCALENDAR\r\n')

        # Components can be nested, so You can add a subcompont. Eg a calendar
        # holds events.
        e = Component(summary='A brief history of time')
        e.name = 'VEVENT'
        e.add('dtend', '20000102T000000', encode=0)
        e.add('dtstart', '20000101T000000', encode=0)
        self.assertEqual(e.to_ical(),
            'BEGIN:VEVENT\r\nDTEND:20000102T000000\r\n'
            + 'DTSTART:20000101T000000\r\nSUMMARY:A brief history of time\r'
            + '\nEND:VEVENT\r\n')

        c.add_component(e)
        self.assertEqual(c.subcomponents,
            [Event({'DTEND': '20000102T000000', 'DTSTART': '20000101T000000',
                    'SUMMARY': 'A brief history of time'})])

        # We can walk over nested componentes with the walk method.
        self.assertEqual([i.name for i in c.walk()], ['VCALENDAR', 'VEVENT'])

        # We can also just walk over specific component types, by filtering
        # them on their name.
        self.assertEqual([i.name for i in c.walk('VEVENT')], ['VEVENT'])

        self.assertEqual([i['dtstart'] for i in c.walk('VEVENT')],
            ['20000101T000000'])

        # We can enumerate property items recursively with the property_items
        # method.
        self.assertEqual(c.property_items(),
            [('BEGIN', 'VCALENDAR'), ('ATTENDEE', prop.vCalAddress('Max M')),
             ('BEGIN', 'VEVENT'), ('DTEND', '20000102T000000'),
             ('DTSTART', '20000101T000000'),
             ('SUMMARY', 'A brief history of time'), ('END', 'VEVENT'),
             ('END', 'VCALENDAR')])

        # We can also enumerate property items just under the component.
        self.assertEqual(c.property_items(recursive=False),
            [('BEGIN', 'VCALENDAR'),
             ('ATTENDEE', prop.vCalAddress('Max M')),
             ('END', 'VCALENDAR')])

        sc = c.subcomponents[0]
        self.assertEqual(sc.property_items(recursive=False),
            [('BEGIN', 'VEVENT'), ('DTEND', '20000102T000000'),
             ('DTSTART', '20000101T000000'),
             ('SUMMARY', 'A brief history of time'), ('END', 'VEVENT')])

        # Text fields which span multiple mulitple lines require proper
        # indenting
        c = Calendar()
        c['description'] = u'Paragraph one\n\nParagraph two'
        self.assertEqual(c.to_ical(),
           'BEGIN:VCALENDAR\r\nDESCRIPTION:Paragraph one\\n\\nParagraph two'
           + '\r\nEND:VCALENDAR\r\n')

        # INLINE properties have their values on one property line. Note the
        # double quoting of the value with a colon in it.
        c = Calendar()
        c['resources'] = 'Chair, Table, "Room: 42"'
        self.assertEqual(c,
            Calendar({'RESOURCES': 'Chair, Table, "Room: 42"'}))

        self.assertEqual(c.to_ical(),
            'BEGIN:VCALENDAR\r\nRESOURCES:Chair\\, Table\\, "Room: 42"\r\n'
            + 'END:VCALENDAR\r\n')

        # The inline values must be handled by the get_inline() and
        # set_inline() methods.
        self.assertEqual(c.get_inline('resources', decode=0),
            ['Chair', 'Table', 'Room: 42'])

        # These can also be decoded
        self.assertEqual(c.get_inline('resources', decode=1),
            [u'Chair', u'Table', u'Room: 42'])

        # You can set them directly ...
        c.set_inline('resources', ['A', 'List', 'of', 'some, recources'],
                     encode=1)
        self.assertEqual(c['resources'], 'A,List,of,"some, recources"')

        # ... and back again
        self.assertEqual(c.get_inline('resources', decode=0),
            ['A', 'List', 'of', 'some, recources'])

        c['freebusy'] = '19970308T160000Z/PT3H,19970308T200000Z/PT1H,'\
                        + '19970308T230000Z/19970309T000000Z'
        self.assertEqual(c.get_inline('freebusy', decode=0),
            ['19970308T160000Z/PT3H', '19970308T200000Z/PT1H',
             '19970308T230000Z/19970309T000000Z'])

        freebusy = c.get_inline('freebusy', decode=1)
        self.assertTrue(isinstance(freebusy[0][0], datetime))
        self.assertTrue(isinstance(freebusy[0][1], timedelta))

    def test_cal_Component_add(self):
        # Test the for timezone correctness: dtstart should preserve it's
        # timezone, crated, dtstamp and last-modified must be in UTC.
        Component = icalendar.cal.Component
        comp = Component()
        comp.add('dtstart', datetime(2010, 10, 10, 10, 0, 0,
                                     tzinfo=pytz.timezone("Europe/Vienna")))
        comp.add('created', datetime(2010, 10, 10, 12, 0, 0))
        comp.add('dtstamp', datetime(2010, 10, 10, 14, 0, 0,
                                     tzinfo=pytz.timezone("Europe/Vienna")))
        comp.add('last-modified', datetime(2010, 10, 10, 16, 0, 0,
                                           tzinfo=pytz.utc))

        lines = comp.to_ical().splitlines()
        self.assertTrue(
            "DTSTART;TZID=Europe/Vienna;VALUE=DATE-TIME:20101010T100000"
            in lines)
        self.assertTrue("CREATED;VALUE=DATE-TIME:20101010T120000Z" in lines)
        self.assertTrue("DTSTAMP;VALUE=DATE-TIME:20101010T130000Z" in lines)
        self.assertTrue(
                "LAST-MODIFIED;VALUE=DATE-TIME:20101010T160000Z" in lines)

    def test_cal_Component_add_no_reencode(self):
        """Already encoded values should not be re-encoded.
        """
        from icalendar import cal, prop
        comp = cal.Component()
        comp.add('ATTACH', 'me')

        comp.add('ATTACH', 'you', encode=False)
        binary = prop.vBinary('us')
        comp.add('ATTACH', binary)

        self.assertEqual(comp['ATTACH'], [u'me', 'you', binary])

    def test_cal_Component_from_ical(self):
        # RecurrenceIDs may contain a TZID parameter, if so, they should create
        # a tz localized datetime, otherwise, create a naive datetime
        Component = icalendar.cal.Component
        componentStr = 'BEGIN:VEVENT\nRECURRENCE-ID;TZID=America/Denver:'\
                       + '20120404T073000\nEND:VEVENT'
        component = Component.from_ical(componentStr)
        self.assertEqual(
            str(component['RECURRENCE-ID'].dt.tzinfo.zone), "America/Denver")

        componentStr = 'BEGIN:VEVENT\nRECURRENCE-ID:20120404T073000\n'\
                       + 'END:VEVENT'
        component = Component.from_ical(componentStr)
        self.assertEqual(component['RECURRENCE-ID'].dt.tzinfo, None)


class TestCal(unittest.TestCase):

    def test_cal_ComponentFactory(self):
        ComponentFactory = icalendar.cal.ComponentFactory
        factory = ComponentFactory()
        component = factory['VEVENT']
        event = component(dtstart='19700101')
        self.assertEqual(event.to_ical(),
            'BEGIN:VEVENT\r\nDTSTART:19700101\r\nEND:VEVENT\r\n')

        self.assertEqual(
            factory.get('VCALENDAR', icalendar.cal.Component),
            icalendar.cal.Calendar)

    def test_cal_Calendar(self):
        # Setting up a minimal calendar component looks like this
        cal = icalendar.cal.Calendar()

        # Some properties are required to be compliant
        cal['prodid'] = '-//My calendar product//mxm.dk//'
        cal['version'] = '2.0'

        # We also need at least one subcomponent for a calendar to be compliant
        event = icalendar.cal.Event()
        event['summary'] = 'Python meeting about calendaring'
        event['uid'] = '42'
        event.set('dtstart', datetime(2005, 4, 4, 8, 0, 0))
        cal.add_component(event)
        self.assertEqual(
            cal.subcomponents[0].to_ical(),
            'BEGIN:VEVENT\r\nSUMMARY:Python meeting about calendaring\r\n'\
            + 'DTSTART;VALUE=DATE-TIME:20050404T080000\r\nUID:42\r\n'\
            + 'END:VEVENT\r\n')

        # Write to disc
        import tempfile, os
        directory = tempfile.mkdtemp()
        open(os.path.join(directory, 'test.ics'), 'wb').write(cal.to_ical())

        # Parsing a complete calendar from a string will silently ignore bogus
        # events. The bogosity in the following is the third EXDATE: it has an
        # empty DATE.
        s = '\r\n'.join(('BEGIN:VCALENDAR',
                         'PRODID:-//Google Inc//Google Calendar 70.9054//EN',
                         'VERSION:2.0',
                         'CALSCALE:GREGORIAN',
                         'METHOD:PUBLISH',
                         'BEGIN:VEVENT',
                         'DESCRIPTION:Perfectly OK event',
                         'DTSTART;VALUE=DATE:20080303',
                         'DTEND;VALUE=DATE:20080304',
                         'RRULE:FREQ=DAILY;UNTIL=20080323T235959Z',
                         'EXDATE;VALUE=DATE:20080311',
                         'END:VEVENT',
                         'BEGIN:VEVENT',
                         'DESCRIPTION:Bogus event',
                         'DTSTART;VALUE=DATE:20080303',
                         'DTEND;VALUE=DATE:20080304',
                         'RRULE:FREQ=DAILY;UNTIL=20080323T235959Z',
                         'EXDATE;VALUE=DATE:20080311',
                         'EXDATE;VALUE=DATE:',
                         'END:VEVENT',
                         'END:VCALENDAR'))
        self.assertEqual(
            [e['DESCRIPTION'].to_ical()
                for e in icalendar.cal.Calendar.from_ical(s).walk('VEVENT')],
            ['Perfectly OK event'])
