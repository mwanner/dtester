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

from twisted.internet import defer, reactor

class EventHook:
    """ A hook on a certain event, which fires a callback.
    """
    def __init__(self, ev_source, matcher, cb):
        self.ev_source = ev_source
        self.matcher = matcher
        self.cb = cb

    def fireCallback(self, event):
        self.cb(event)

class EventSource:
    """ An abstract object representing any kind of process, workflow or
        background job that emits L{events<Event>}.
    """
    def __init__(self):
        self.hooks = set()

    def throwEvent(self, eventClass, *args, **kwargs):
        event = eventClass(self, *args, **kwargs)
        for hook in self.hooks:
            if hook.matcher.matches(event):
                reactor.callLater(0.0, hook.fireCallback, event)

    def addHook(self, matcher, callback):
        assert callable(callback), "callback function must be callable"
        newHook = EventHook(self, matcher, callback)
        self.hooks.add(newHook)
        return newHook

    def removeHook(self, hook):
        assert hook in self.hooks
        self.hooks.remove(hook)

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
    def __init__(self, eventClass, *args, **kwargs):
        self.eventClass = eventClass
        self.args = args
        self.kwargs = kwargs
        self.defer = defer.Deferred()

    def getDefer(self):
        return self.defer

    def matches(self, event):
        if isinstance(event, self.eventClass):
            return event.matches(*self.args, **self.kwargs)


class StreamDataEvent(Event):
    """ An abstract class for events thrown by L{SimpleProcess} for every kind
        of output to any channel.
    """

    name = 'DataEvent'

    def __init__(self, source, data):
        Event.__init__(self, source)
        self.data = data

    def matches(self, pattern=None):
        if pattern:
            return (self.data.find(pattern) >= 0)
        else:
            return True

    def __repr__(self):
        return "[%s] %s: %s" % (self.source, self.name, self.data)


class ProcessOutStreamEvent(StreamDataEvent):
    """ The event thrown by L{SimpleProcess} for every output to its standard
        output channel.
    """

    name = 'out'


class ProcessErrStreamEvent(StreamDataEvent):
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

