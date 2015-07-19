from django.template import RequestContext, loader
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
import arsoft.openvpn
from arsoft.timestamp import UTC, format_timedelta

import datetime

# import the logging library
import logging

# Get an instance of a logger
logger = logging.getLogger(__name__)

class ConfigCertItem(object):
    def __init__(self, cert_file_obj):
        self._cert_file_obj = cert_file_obj
        if self._cert_file_obj.certificates:
            self._cert_obj = self._cert_file_obj.certificates[0]
            now = datetime.datetime.utcnow().replace(tzinfo=UTC)
            min_expire_in = datetime.timedelta(days=100*365)
            min_expire_cert = None
            for cert in self._cert_file_obj.certificates:
                expire_in = cert.expire_date - now
                if expire_in < min_expire_in:
                    min_expire_in = expire_in
                    min_expire_cert = cert

        else:
            self._cert_obj = None
        self.filename = self._cert_file_obj.filename
        self.subject = 'CN=%s' % self._cert_obj.subject.commonName if self._cert_obj else None
        self.issuer = 'CN=%s' % self._cert_obj.issuer.commonName if self._cert_obj else None
        if min_expire_cert:
            if min_expire_in.total_seconds() < 0:
                self.expire_date = str(min_expire_cert.expire_date) + ' was ' + format_timedelta(min_expire_in)
            else:
                self.expire_date = str(min_expire_cert.expire_date) + ' in ' + format_timedelta(min_expire_in)
        else:
            self.expire_date = 'unavailable'


class ConfigItem(object):
    def __init__(self, hub, config_file):
        self.hub = hub
        self.config_file = config_file
        self.name = self.config_file.name
        self.filename = self.config_file.filename
        self.is_running = self.hub.config.is_running(self.name)
        self.autostart = True if self.name in self.hub.systemconfig.autostart else False
        self.status_file_obj = arsoft.openvpn.StatusFile(config_file=self.config_file)
        self.status_version = self.config_file.status_version
        self.status_file = self.config_file.status_file
        self.logfile = self.config_file.logfile if self.config_file.logfile else self.config_file.logfile_append
        self.server = self.config_file.server
        self.routes = []
        for (network, netmask) in self.config_file.routes:
            self.routes.append( '%s/%s' % (network, netmask))
        self.routing_table = []
        if self.status_file_obj.routing_table:
            logger.error('%s routing_table=%s' % (self.name, self.status_file_obj.routing_table))
            for entry in self.status_file_obj.routing_table:
                self.routing_table.append(str(entry))

        self.certificate = ConfigCertItem(self.config_file.cert_file)

        self.client_config_directory = self.config_file.client_config_directory if self.server else None
        self.connection_state = self.status_file_obj.state.long_state
        self.connected_clients = []
        self.configured_clients = []
        if self.server:
            if self.status_file_obj.connected_clients:
                for (clientname, clientinfo) in self.status_file_obj.connected_clients.iteritems():
                    self.connected_clients.append(str(clientinfo))
            if self.config_file.client_config_files:
                for (clientname, ccdfile) in self.config_file.client_config_files.iteritems():
                    self.configured_clients.append(clientname)



class ConfigHub(object):
    def __init__(self):
        self.config = arsoft.openvpn.Config()
        self.systemconfig = arsoft.openvpn.SystemConfig()

    def list(self, selected_vpns=[]):
        ret = []
        if not selected_vpns:
            selected_vpns = self.config.names

        logger.error('self.config.names=%s' % self.config.names)
        logger.error('selected_vpns=%s' % selected_vpns)
        for vpnname in selected_vpns:
            item = ConfigItem(self, arsoft.openvpn.ConfigFile(config_name=vpnname))
            ret.append(item)
        return ret

def home(request):

    hub = ConfigHub()
    title = 'OpenVPN status'

    logger.error('config_list=%s' % hub.list())

    t = loader.get_template('home.html')
    c = RequestContext( request, { 
        'config_list':hub.list(),
        'title':title
        })
    return HttpResponse(t.render(c))

