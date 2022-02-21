#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil

from dnx_gentools.def_constants import HOME_DIR
from dnx_gentools.def_typing import *
from dnx_gentools.file_operations import ConfigurationManager, load_configuration, write_configuration, calculate_file_hash

from dnx_routines.logging.log_client import Log

DEFAULT_VERSION: str = 'firewall_pending'
DEFAULT_PATH: str = 'dnx_system/iptables'
USER_PATH: str = f'{DEFAULT_PATH}/usr'

PENDING_RULE_FILE: str = f'{HOME_DIR}/{DEFAULT_PATH}/usr/firewall_pending.cfg'
ACTIVE_RULE_FILE:  str = f'{HOME_DIR}/{DEFAULT_PATH}/usr/firewall_active.cfg'
COPY_RULE_FILE:    str = f'{HOME_DIR}/{DEFAULT_PATH}/usr/firewall_copy.cfg'

ConfigurationManager.set_log_reference(Log)

# ========================================
# MANAGE - used by webui
# ========================================
class FirewallManage:
    '''intermediary between frontend and underlying C rules code.

    Front end <> FirewallManage <file monitoring> FirewallControl <> CFirewall

    rules = FirewallManage()
    print(rules.view_ruleset())

    print(rules.view_ruleset('BEFORE'))

    '''

    __slots__ = ()

    # store the main instances reference here, so it can be accessed throughout webui
    cfirewall: ClassVar[Optional[CFirewall]] = None
    object_manager: ClassVar[Optional[ObjectManager]] = None

    versions: ClassVar[list] = ['pending', 'active']
    sections: ClassVar[list] = ['BEFORE', 'MAIN', 'AFTER']

    _firewall: ClassVar[dict] = load_configuration(DEFAULT_VERSION, filepath=USER_PATH).get_dict()

    @classmethod
    def commit(cls, firewall_rules: dict) -> None:
        '''Updates pending configuration file with sent in firewall rules data.

        This is a replace operation on disk and thread and process safe.'''

        with ConfigurationManager(DEFAULT_VERSION, file_path=USER_PATH) as dnx_fw:
            dnx_fw.write_configuration(firewall_rules)

        # updating instance/ mem-copy of variable for fast access
        cls._firewall = firewall_rules

    @classmethod
    def push(cls) -> None:
        '''Copy the pending configuration to the active state.

        file changes are being monitored by Control class to load into cfirewall.'''

        with ConfigurationManager():
            shutil.copy(PENDING_RULE_FILE, COPY_RULE_FILE)

            # ==============================
            # OBJECT ID > VALUE CONVERSIONS
            # ==============================
            obj_lookup = cls.object_manager.lookup

            # using standalone functions due to ConfigManager not being compatible with these operations
            fw_rules = load_configuration('firewall_pending', filepath='dnx_system/iptables')

            fw_rule_copy = fw_rules.get_dict()

            for section in cls.sections:

                for rule in fw_rule_copy[section].values():
                    rule['src_network'] = [obj_lookup(x, convert=True) for x in rule['src_network']]
                    rule['src_service'] = [obj_lookup(x, convert=True) for x in rule['src_service']]

                    rule['dst_network'] = [obj_lookup(x, convert=True) for x in rule['dst_network']]
                    rule['dst_service'] = [obj_lookup(x, convert=True) for x in rule['dst_service']]

            write_configuration(fw_rule_copy, 'firewall_copy', filepath='dnx_system/iptables')

            print('FUTURE ACTIVE', fw_rules)

#            os.replace(COPY_RULE_FILE, ACTIVE_RULE_FILE)

    @staticmethod
    def revert():
        '''Copies active configuration to pending, which effectively wipes any unpushed changes.'''

        with ConfigurationManager():
            shutil.copy(ACTIVE_RULE_FILE, COPY_RULE_FILE)

            os.replace(COPY_RULE_FILE, PENDING_RULE_FILE)

    def convert_ruleset(self):
        pass

    def view_ruleset(self, section='MAIN'):
        '''returns dict of requested "firewall_pending" ruleset in raw form.

        additional processing is required for webui or cli formats.
        the section arg will change which ruleset is returned.
        '''

        try:
            return self._firewall[section]
        except KeyError:
            return {}

    def ruleset_len(self, section='MAIN'):
        '''returns len of firewall_pending ruleset. defaults to main and returns 0 on error.'''

        try:
            return len(self._firewall[section])
        except:
            return 0

    @staticmethod
    def is_pending_changes():
        active = calculate_file_hash('firewall_active.cfg', folder='iptables/usr')
        pending = calculate_file_hash('firewall_pending.cfg', folder='iptables/usr')

        # if the user has never modified rules, there is not a pending change. the active file can be none if pending is
        # present. a commit will write the active file.
        if (pending is None):
            return False

        return active != pending

# class FirewallManageLegacy:
#     '''intermediary between front end and underlying C firewall code.
#
#     Front end <> FirewallManageLegacy <file monitoring> FirewallControl <> CFirewall
#
#     '''
#
#     __slots__ = (
#         '_firewall',
#     )
#
#     # store main instance reference here, so it can be accessed throughout webui
#     cfirewall = None
#
#     versions = ['pending', 'active']
#     sections = ['BEFORE', 'MAIN', 'AFTER']
#
#     def __init__(self):
#         self._firewall = load_configuration(DEFAULT_VERSION, filepath=DEFAULT_PATH)
#
#     def add(self, pos, rule, *, section):
#         '''insert or append operation of new rules rule to the specified section.'''
#
#         # for comparison operators, but will use str as key as required for json.
#         pos_int = int(pos)
#
#         with ConfigurationManager(DEFAULT_VERSION, file_path=DEFAULT_PATH) as dnx_fw:
#             rules = dnx_fw.load_configuration()
#
#             ruleset = rules[section]
#
#             # position is at the beginning of the ruleset. this is needed because the slice functions don't work
#             # correctly for pos 1 insertions.
#             if (pos_int == 1):
#                 temp_rules = [rule, *ruleset.values()]
#
#                 # assigning section with new ruleset
#                 rules[section] = {f'{i}': rule for i, rule in enumerate(temp_rules, 1)}
#
#             # position is after last element so can add to end of dict directly.
#             elif (pos_int == len(ruleset) + 1):
#                 ruleset[pos] = rule
#
#             # position falls somewhere within already allocated memory. using slices to split open position.
#             else:
#                 temp_rules = list(ruleset.values())
#
#                 # offset to adjust for rule num vs index
#                 temp_rules.insert(pos_int-1, rule)
#
#                 # assigning section with new ruleset
#                 rules[section] = {f'{i}': rule for i, rule in enumerate(temp_rules, 1)}
#
#             dnx_fw.write_configuration(rules)
#
#             # updating instance/ mem-copy of variable for fast access
#             self._firewall = rules
#
#     def remove(self, pos, *, section):
#
#         with ConfigurationManager(DEFAULT_VERSION, file_path=DEFAULT_PATH) as dnx_fw:
#             rules = dnx_fw.load_configuration()
#
#             ruleset = rules[section]
#
#             # this is safe if it fails because the context will immediately exit gracefully
#             ruleset.pop(pos)
#
#             rules[section] = {f'{i}': rule for i, rule in enumerate(ruleset.values(), 1)}
#
#             dnx_fw.write_configuration(rules)
#
#             # updating instance/ mem-copy of variable for fast access
#             self._firewall = rules
#
#     def modify(self, static_pos, pos, rule, *, section):
#         '''send new definition of rule and rule position to underlying rules to be updated.
#
#             section (rule type): BEFORE, MAIN, AFTER (will likely be an enum)
#         '''
#
#         move = True if pos != static_pos else False
#
#         with ConfigurationManager(DEFAULT_VERSION, file_path=DEFAULT_PATH) as dnx_fw:
#             rules = dnx_fw.load_configuration()
#
#             ruleset = rules[section]
#
#             # TODO: make lock re entrant (non exclusive?)
#             # update rule first using static_pos, then remove from list if it needs to move. cannot call add method
#             from here due to file lock being held by this current context (its not re entrant).
#             ruleset[static_pos] = rule
#             if (move):
#                 rule_to_move = ruleset.pop(static_pos)
#
#             # writes even if it needs to move since external func will handle move operation (in the form of
#             insertion). dnx_fw.write_configuration(rules)
#
#             # updating instance/ mem-copy of variable for fast access
#             self._firewall = rules
#
#         # now that we are out of the context we can use add method to re-insert the rule in specified place
#         # NOTE: since the lock has been released it is possible for another process to get the lock and modify rules
#         #  rules before the move can happen. only on rare cases would this even cause an issue and only the pending
#         #  config will be effected and can be reverted if need be. in the future maybe we can figure out a way to deal
#         #  with this operation without releasing the lock without having to duplicate code.
#         if (move):
#             self.add(pos, rule_to_move, section=section)
