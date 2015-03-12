# events.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
definition of events, their sources and matchers as well as some event
classes
"""

from twisted.internet import defer

class EventSource:
    """ An abstract object representing any kind of process, workflow or
        background job that emits L{events<Event>}.
    """
    def __init__(self):
        self.hooks = {}
        self.maxHookId = 0

    def throwEvent(self, eventClass, *args, **kargs):
        event = eventClass(self, *args, **kargs)
        for hid, hook in self.hooks.items():
            if hook[0].matches(event):
                hook[1](event, *hook[2], **hook[3])

    def addHook(self, matcher, callback, *args, **kargs):
        assert callable(callback), "callback function must be callable"
        self.maxHookId += 1
        self.hooks[self.maxHookId] = (matcher, callback, args, kargs)
        return self.maxHookId

    def removeHook(self, maxHookId):
        del self.hooks[maxHookId]

class Event:
    """ Base class for all events.
    """
    def __init__(self, source):
        self.source = source

    def matches(self):
        return True

    def __repr__(self):
        return "Event of type %s from %s" % (self.__class__, self.source)

class EventMatcher(object):
    """ A matcher that compares L{events<Event>} against a certain criterion.
    """
    def __init__(self, eventClass, *args, **kargs):
        self.eventClass = eventClass
        self.args = args
        self.defer = defer.Deferred()

    def getDefer(self):
        return self.defer

    def matches(self, event):
        if isinstance(event, self.eventClass):
            return event.matches(*self.args)


class StreamDataEvent(Event):
    """ An abstract class for events thrown by L{SimpleProcess} for every kind
        of output to any channel.
    """

    name = 'DataEvent'

    def __init__(self, source, data):
        Event.__init__(self, source)
        self.data = data

    def matches(self, needle=None):
        if needle:
            return (self.data.find(needle) >= 0)
        else:
            return True

    def __repr__(self):
        return "[%s] %s: %s" % (self.source, self.name, self.data)


class ProcessOutputEvent(StreamDataEvent):
    """ The event thrown by L{SimpleProcess} for every output to its standard
        output channel.
    """

    name = 'out'


class ProcessErrorEvent(StreamDataEvent):
    """ The event thrown by L{SimpleProcess} for every output to its standard
        error channel.
    """

    name = 'err'


class ProcessEndedEvent(Event):
    """ The event thrown by L{SimpleProcess} as soon as the controlled
        process has terminated.
    """

    name = 'terminated'

    def __init__(self, source, exitCode):
        Event.__init__(self, source)
        self.exitCode = exitCode

    def __repr__(self):
        return "[%s] terminated with error code %s" % (
            self.source, self.exitCode)




class RemoteStreamDataEvent(Event):
    """ An abstract class for events emitted by
        L{RemoteProcessExecutionChannel} for every kind of output to any
        channel.
    """

    name = 'RemoteDataEvent'

    def __init__(self, source, data):
        Event.__init__(self, source)
        self.data = data

    def matches(self, needle=None):
        if needle:
            return (self.data.find(needle) >= 0)
        else:
            return True

    def __repr__(self):
        return "[%s] %s: %s" % (self.source, self.name, self.data)


class RemoteProcessOutputEvent(RemoteStreamDataEvent):
    """ The event thrown by L{SimpleProcess} for every output to its standard
        output channel.
    """

    name = 'out'


class RemoteProcessErrorEvent(RemoteStreamDataEvent):
    """ The event thrown by L{SimpleProcess} for every output to its standard
        error channel.
    """

    name = 'err'

