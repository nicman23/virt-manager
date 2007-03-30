#
# Copyright (C) 2006-2007 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import gtk
import gtk.gdk
import gtk.glade
import libvirt
import virtinst
import os, sys
import logging
import dbus
import re

from virtManager.IPy import IP

PAGE_INTRO = 0
PAGE_NAME = 1
PAGE_IPV4 = 2
PAGE_DHCP = 3
PAGE_FORWARDING = 4
PAGE_SUMMARY = 5


class vmmCreateNetwork(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, conn):
        self.__gobject_init__()
        self.config = config
        self.conn = conn
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-create-net.glade", "vmm-create-net", domain="virt-manager")
        self.topwin = self.window.get_widget("vmm-create-net")
        self.topwin.hide()
        self.window.signal_autoconnect({
            "on_create_pages_switch_page" : self.page_changed,
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_net_forward_toggled" : self.change_forward_type,
            "on_net_network_changed": self.change_network,
            "on_net_dhcp_start_changed": self.change_dhcp_start,
            "on_net_dhcp_end_changed": self.change_dhcp_end,
            "on_create_help_clicked": self.show_help,
            })

        self.set_initial_state()

    def show(self):
        self.topwin.show()
        self.reset_state()
        self.topwin.present()

    def set_initial_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_show_tabs(False)

        #XXX I don't think I should have to go through and set a bunch of background colors
        # in code, but apparently I do...
        black = gtk.gdk.color_parse("#000")
        for num in range(PAGE_SUMMARY+1):
            name = "page" + str(num) + "-title"
            self.window.get_widget(name).modify_bg(gtk.STATE_NORMAL,black)

        # set up the list for the cd-path widget
        fw_list = self.window.get_widget("net-forward")
        # Fields are raw device path, volume label, flag indicating
        # whether volume is present or not, and HAL path
        fw_model = gtk.ListStore(str, bool, str)
        fw_list.set_model(fw_model)
        text = gtk.CellRendererText()
        fw_list.pack_start(text, True)
        fw_list.add_attribute(text, 'text', 1)
        try:
            # Get a connection to the SYSTEM bus
            self.bus = dbus.SystemBus()
            # Get a handle to the HAL service
            hal_object = self.bus.get_object('org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object, 'org.freedesktop.Hal.Manager')
            self.populate_opt_media(net_model)
        except Exception, e:
            logging.error("Unable to connect to HAL to list cdrom volumes: '%s'", e)
            self.bus = None
            self.hal_iface = None


    def reset_state(self):
        notebook = self.window.get_widget("create-pages")
        notebook.set_current_page(0)
        # Hide the "finish" button until the appropriate time
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        self.window.get_widget("create-back").set_sensitive(False)

        self.window.get_widget("net-name").set_text("")
        self.window.get_widget("net-network").set_text("192.168.100.0/24")
        self.window.get_widget("net-dhcp-start").set_text("")
        self.window.get_widget("net-dhcp-end").set_text("")
        self.window.get_widget("net-forward-none").set_active(True)


    def forward(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        if(self.validate(notebook.get_current_page()) != True):
            return

        notebook.next_page()

    def back(self, ignore=None):
        notebook = self.window.get_widget("create-pages")
        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-finish").hide()
        self.window.get_widget("create-forward").show()
        notebook.prev_page()

    def change_network(self, src):
        ip = self.get_config_ip4()
        green = gtk.gdk.color_parse("#c0ffc0")
        red = gtk.gdk.color_parse("#ffc0c0")
        black = gtk.gdk.color_parse("#000000")
        src.modify_text(gtk.STATE_NORMAL, black)
        if ip is None or ip.version() != 4:
            print str(ip)
            src.modify_base(gtk.STATE_NORMAL, red)
            self.window.get_widget("net-info-netmask").set_text("")
            self.window.get_widget("net-info-broadcast").set_text("")
            self.window.get_widget("net-info-gateway").set_text("")
            self.window.get_widget("net-info-size").set_text("")
            self.window.get_widget("net-info-type").set_text("")
        else:
            if ip.len() < 16 or ip.iptype() != "PRIVATE":
                src.modify_base(gtk.STATE_NORMAL, red)
            else:
                src.modify_base(gtk.STATE_NORMAL, green)
            self.window.get_widget("net-info-netmask").set_text(str(ip.netmask()))
            self.window.get_widget("net-info-broadcast").set_text(str(ip.broadcast()))
            if ip.len() <= 1:
                self.window.get_widget("net-info-gateway").set_text("")
            else:
                self.window.get_widget("net-info-gateway").set_text(str(ip[1]))
            self.window.get_widget("net-info-size").set_text(_("%d addresses") % (ip.len()))
            if ip.iptype() == "PUBLIC":
                self.window.get_widget("net-info-type").set_text(_("Public"))
            elif ip.iptype() == "PRIVATE":
                self.window.get_widget("net-info-type").set_text(_("Private"))
            elif ip.iptype() == "RESERVED":
                self.window.get_widget("net-info-type").set_text(_("Reserved"))
            else:
                self.window.get_widget("net-info-type").set_text(_("Other"))

    def change_dhcp_start(self, src):
        end = self.get_config_dhcp_start()
        self.change_dhcp(src, end)

    def change_dhcp_end(self, src):
        end = self.get_config_dhcp_end()
        self.change_dhcp(src, end)

    def change_dhcp(self, src, addr):
        ip = self.get_config_ip4()
        black = gtk.gdk.color_parse("#000000")
        src.modify_text(gtk.STATE_NORMAL, black)

        if addr is None or not ip.overlaps(addr):
            red = gtk.gdk.color_parse("#ffc0c0")
            src.modify_base(gtk.STATE_NORMAL, red)
        else:
            green = gtk.gdk.color_parse("#c0ffc0")
            src.modify_base(gtk.STATE_NORMAL, green)

    def change_forward_type(self, src):
        pass

    def get_config_name(self):
        return self.window.get_widget("net-name").get_text()

    def get_config_ip4(self):
        try:
            return IP(self.window.get_widget("net-network").get_text())
        except:
            return None

    def get_config_dhcp_start(self):
        try:
            return IP(self.window.get_widget("net-dhcp-start").get_text())
        except:
            return None
    def get_config_dhcp_end(self):
        try:
            return IP(self.window.get_widget("net-dhcp-end").get_text())
        except:
            return None


    def get_config_forwarding(self):
        if self.window.get_widget("net-forward-none").get_active():
            return [False, None]
        else:
            dev = self.window.get_widget("net-forward-dev")
            # XXX dev
            return [True, None]

    def page_changed(self, notebook, page, page_number):
        # would you like some spaghetti with your salad, sir?

        if page_number == PAGE_INTRO:
            self.window.get_widget("create-back").set_sensitive(False)
        elif page_number == PAGE_NAME:
            name_widget = self.window.get_widget("net-name")
            name_widget.grab_focus()
        elif page_number == PAGE_IPV4:
            pass
        elif page_number == PAGE_DHCP:
            ip = self.get_config_ip4()
            start = int(ip.len() / 2)
            end = ip.len()-2
            if self.window.get_widget("net-dhcp-start").get_text() == "":
                self.window.get_widget("net-dhcp-start").set_text(str(ip[start]))
            if self.window.get_widget("net-dhcp-end").get_text() == "":
                self.window.get_widget("net-dhcp-end").set_text(str(ip[end]))
        elif page_number == PAGE_FORWARDING:
            pass
        elif page_number == PAGE_SUMMARY:
            self.window.get_widget("summary-name").set_text(self.get_config_name())

            ip = self.get_config_ip4()
            self.window.get_widget("summary-ip4-network").set_text(str(ip))
            self.window.get_widget("summary-ip4-gateway").set_text(str(ip[1]))
            self.window.get_widget("summary-ip4-netmask").set_text(str(ip.netmask()))

            start = self.get_config_dhcp_start()
            end = self.get_config_dhcp_end()
            self.window.get_widget("summary-dhcp-start").set_text(str(start))
            self.window.get_widget("summary-dhcp-end").set_text(str(end))

            fw = self.get_config_forwarding()
            if fw[0]:
                self.window.get_widget("summary-forwarding").set_text(_("Isolated virtual network"))
            else:
                if fw[1] is not None:
                    self.window.get_widget("summary-forwarding").set_text(_("NAT to physical device %s") % (fw[1]))
                else:
                    self.window.get_widget("summary-forwarding").set_text(_("Masquerading via default route"))

            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()

    def close(self, ignore1=None,ignore2=None):
        self.topwin.hide()
        return 1

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
           return 1
        return 0

    def finish(self, ignore=None):
        name = self.get_config_name()
        ip = self.get_config_ip4()
        start = self.get_config_dhcp_start()
        end = self.get_config_dhcp_end()
        fw = self.get_config_forwarding()

        xml = "<network>" + \
              "  <name>%s</name>\n" % name
        if fw[0]:
            if fw[1] is not None:
                xml += "  <forward dev='%s'/>\n" % fw[1]
            else:
                xml += "  <forward/>\n"

        xml += "  <ip address='%s' netmask='%s'>\n" % (str(ip[1]), str(ip.netmask()))
        xml += "    <dhcp>\n"
        xml += "      <range start='%s' end='%s'/>\n" % (str(start), str(end))
        xml += "    </dhcp>\n"
        xml += "  </ip>\n"
        xml += "</network>\n"

        logging.debug("About to create network " + xml)

        self.conn.create_network(xml)
        self.close()

    def validate(self, page_num):
        if page_num == PAGE_NAME:
            name = self.window.get_widget("net-name").get_text()
            if len(name) > 50 or len(name) == 0:
                self._validation_error_box(_("Invalid Network Name"), \
                                           _("Network name must be non-blank and less than 50 characters"))
                return False
            if re.match("^[a-zA-Z0-9_]*$", name) == None:
                self._validation_error_box(_("Invalid Network Name"), \
                                           _("Network name may contain alphanumeric and '_' characters only"))
                return False


        elif page_num == PAGE_IPV4:
            ip = self.get_config_ip4()
            if ip is None:
                self._validation_error_box(_("Invalid Network Address"), \
                                           _("The network address could not be understood"))
                return False

            if ip.version() != 4:
                self._validation_error_box(_("Invalid Network Address"), \
                                           _("The network must be an IPv4 address"))
                return False

            if ip.len() < 16:
                self._validation_error_box(_("Invalid Network Address"), \
                                           _("The network prefix must be at least /4 (16 addresses)"))
                return False

            if ip.iptype() != "PRIVATE":
                self._validation_error_box(_("Invalid Network Address"), \
                                           _("The network must be an IPv4 private address"))
                return False
        elif page_num == PAGE_DHCP:
            ip = self.get_config_ip4()
            start = self.get_config_dhcp_start()
            end = self.get_config_dhcp_end()

            if start is None:
                self._validation_error_box(_("Invalid DHCP Address"), \
                                           _("The DHCP start address could not be understood"))
                return False
            if end is None:
                self._validation_error_box(_("Invalid DHCP Address"), \
                                           _("The DHCP end address could not be understood"))
                return False

            if not ip.overlaps(start):
                self._validation_error_box(_("Invalid DHCP Address"), \
                                           _("The DHCP start address is not with the network %s") % (str(ip)))
                return False
            if not ip.overlaps(end):
                self._validation_error_box(_("Invalid DHCP Address"), \
                                           _("The DHCP end address is not with the network %s") % (str(ip)))
                return False
        elif page_num == PAGE_FORWARDING:
            pass

        # do this always, since there's no "leaving a notebook page" event.
        self.window.get_widget("create-back").set_sensitive(True)
        return True

    def _validation_error_box(self, text1, text2=None):
        message_box = gtk.MessageDialog(self.window.get_widget("vmm-create-net"), \
                                                0, \
                                                gtk.MESSAGE_ERROR, \
                                                gtk.BUTTONS_OK, \
                                                text1)
        if text2 != None:
            message_box.format_secondary_text(text2)
        message_box.run()
        message_box.destroy()

    def populate_opt_media(self, model):
        # get a list of optical devices with data discs in, for FV installs
        vollabel = {}
        volpath = {}
        # Track device add/removes so we can detect newly inserted CD media
        self.hal_iface.connect_to_signal("DeviceAdded", self._device_added)
        self.hal_iface.connect_to_signal("DeviceRemoved", self._device_removed)

        # Find info about all current present media
        for d in self.hal_iface.FindDeviceByCapability("volume"):
            vol = self.bus.get_object("org.freedesktop.Hal", d)
            if vol.GetPropertyBoolean("volume.is_disc") and \
                   vol.GetPropertyBoolean("volume.disc.has_data"):
                devnode = vol.GetProperty("block.device")
                label = vol.GetProperty("volume.label")
                if label == None or len(label) == 0:
                    label = devnode
                vollabel[devnode] = label
                volpath[devnode] = d


        for d in self.hal_iface.FindDeviceByCapability("storage.cdrom"):
            dev = self.bus.get_object("org.freedesktop.Hal", d)
            devnode = dev.GetProperty("block.device")
            if vollabel.has_key(devnode):
                model.append([devnode, vollabel[devnode], True, volpath[devnode]])
            else:
                model.append([devnode, _("No media present"), False, None])

    def show_help(self, src):
        # help to show depends on the notebook page, yahoo
        page = self.window.get_widget("create-pages").get_current_page()
        if page == PAGE_INTRO:
            self.emit("action-show-help", "virt-manager-create-net-intro")
        elif page == PAGE_NAME:
            self.emit("action-show-help", "virt-manager-create-net-name")
        elif page == PAGE_IPV4:
            self.emit("action-show-help", "virt-manager-create-net-ipv4")
        elif page == PAGE_DHCP:
            self.emit("action-show-help", "virt-manager-create-net-dhcp")
        elif page == PAGE_FORWARDING:
            self.emit("action-show-help", "virt-manager-create-net-forwarding")
        elif page == PAGE_SUMMARY:
            self.emit("action-show-help", "virt-manager-create-net-sumary")

