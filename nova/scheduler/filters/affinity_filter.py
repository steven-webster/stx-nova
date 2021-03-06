# Copyright 2012, Piston Cloud Computing, Inc.
# Copyright 2012, OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Copyright (c) 2013-2017 Wind River Systems, Inc.
#


import netaddr
from oslo_log import log as logging

from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)


class DifferentHostFilter(filters.BaseHostFilter):
    """Schedule the instance on a different host from a set of instances."""
    # The hosts the instances are running on doesn't change within a request
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        affinity_uuids = spec_obj.get_scheduler_hint('different_host')
        if affinity_uuids:
            overlap = utils.instance_uuids_overlap(host_state, affinity_uuids)
            if overlap:
                msg = ('found in hosts: %(uuids)s' %
                       {'uuids': ','.join(map(str, affinity_uuids))})
                self.filter_reject(host_state, spec_obj, msg)
            return not overlap
        # With no different_host key
        return True


class SameHostFilter(filters.BaseHostFilter):
    """Schedule the instance on the same host as another instance in a set of
    instances.
    """
    # The hosts the instances are running on doesn't change within a request
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        affinity_uuids = spec_obj.get_scheduler_hint('same_host')
        if affinity_uuids:
            overlap = utils.instance_uuids_overlap(host_state, affinity_uuids)
            if not overlap:
                msg = ('not found in hosts: %(uuids)s' %
                       {'uuids': ','.join(map(str, affinity_uuids))})
                self.filter_reject(host_state, spec_obj, msg)
            return overlap
        # With no same_host key
        return True


class SimpleCIDRAffinityFilter(filters.BaseHostFilter):
    """Schedule the instance on a host with a particular cidr"""
    # The address of a host doesn't change within a request
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        affinity_cidr = spec_obj.get_scheduler_hint('cidr', '/24')
        affinity_host_addr = spec_obj.get_scheduler_hint('build_near_host_ip')
        host_ip = host_state.host_ip
        if affinity_host_addr:
            affinity_net = netaddr.IPNetwork(str.join('', (affinity_host_addr,
                                                           affinity_cidr)))

            retval = netaddr.IPAddress(host_ip) in affinity_net
            if not retval:
                msg = ('host ip %(ip)s not in network %(net)s' %
                       {'ip': host_ip, 'net': affinity_net})
                self.filter_reject(host_state, spec_obj, msg)
            return retval

        # We don't have an affinity host address.
        return True


class _GroupAntiAffinityFilter(filters.BaseHostFilter):
    """Schedule the instance on a different host from a set of group
    hosts.
    """

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        # Only invoke the filter if 'anti-affinity' is configured
        policies = (spec_obj.instance_group.policies
                    if spec_obj.instance_group else [])
        if self.policy_name not in policies:
            return True
        # NOTE(hanrong): Move operations like resize can check the same source
        # compute node where the instance is. That case, AntiAffinityFilter
        # must not return the source as a non-possible destination.
        if spec_obj.instance_uuid in host_state.instances.keys():
            return True

        group_hosts = (spec_obj.instance_group.hosts
                       if spec_obj.instance_group else [])
        LOG.info("Group anti affinity: check if %(host)s not "
                  "in %(configured)s", {'host': host_state.host,
                                        'configured': group_hosts})
        if group_hosts:
            retval = host_state.host not in group_hosts
            if not retval:
                hints = {}
                if spec_obj.obj_attr_is_set('scheduler_hints'):
                    hints = spec_obj.scheduler_hints or {}
                msg = ('Anti-affinity server group specified, but this host'
                       ' is already used by that group: '
                       '%(configured)s, hint=%(hint)s' %
                       {'configured': ', '.join(map(str, group_hosts)),
                        'hint': hints})
                self.filter_reject(host_state, spec_obj, msg)
            return retval

        # No groups configured
        return True


class ServerGroupAntiAffinityFilter(_GroupAntiAffinityFilter):
    def __init__(self):
        self.policy_name = 'anti-affinity'
        super(ServerGroupAntiAffinityFilter, self).__init__()


class _GroupAffinityFilter(filters.BaseHostFilter):
    """Schedule the instance on to host from a set of group hosts.
    """

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        # Only invoke the filter if 'affinity' is configured
        policies = (spec_obj.instance_group.policies
                    if spec_obj.instance_group else [])
        if self.policy_name not in policies:
            return True

        group_hosts = (spec_obj.instance_group.hosts
                       if spec_obj.instance_group else [])
        LOG.debug("Group affinity: check if %(host)s in "
                  "%(configured)s", {'host': host_state.host,
                                     'configured': group_hosts})
        if group_hosts:
            retval = host_state.host in group_hosts
            if not retval:
                filter_properties = spec_obj.to_legacy_filter_properties_dict()
                hints = filter_properties.get('scheduler_hints', {})
                msg = ('not found in: %(configured)s, hint=%(hint)s' %
                       {'configured': ', '.join(map(str, group_hosts)),
                        'hint': hints})
                self.filter_reject(host_state, spec_obj, msg)
            return retval

        # No groups configured
        return True


class ServerGroupAffinityFilter(_GroupAffinityFilter):
    def __init__(self):
        self.policy_name = 'affinity'
        super(ServerGroupAffinityFilter, self).__init__()
