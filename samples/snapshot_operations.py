#!/usr/bin/env python

# Copyright 2016 Abdul Anshad <abdulanshad33@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""
Written by Abdul Anshad
Github: https://github.com/Abdul-Anshad-A
Email: abdulanshad33@gmail.com

Credits:
Thanks to "reuben.13@gmail.com" for the initial code.

Note: Example code For testing purposes only
vSphere Python SDK program to perform snapshot operations.


2020-12-17
Extended by Chris Ebersbach <github-dsce42@fuerdiemenschen.de>
- Added
  - in main(): try section for connect to vsphere section
  - script args:
     - --vm_name
     - --snapshot_operation
     - --snapshot_name
     - --snapshot_description
     - --ignore_ssl
     - --verbose
  - replaced:
     - static "inputs" dict with (values of) those args
"""

import atexit
import argparse
import sys
import time
import ssl
import getpass

from pyVmomi import vim, vmodl
from pyVim.task import WaitForTask
from pyVim import connect
from pyVim.connect import Disconnect, SmartConnect, GetSi

def get_args():
    """Get command line args from the user.
    """
    parser = argparse.ArgumentParser(
        description='Standard Arguments for talking to vCenter')

    # because -h is reserved for 'help' we use -s for service
    parser.add_argument('-s', '--host',
                        required=True,
                        action='store',
                        help='vSphere service to connect to')

    # because we want -p for password, we use -o for port
    parser.add_argument('-o', '--port',
                        type=int,
                        default=443,
                        action='store',
                        help='Port to connect on')

    parser.add_argument('-u', '--user',
                        required=True,
                        action='store',
                        help='User name to use when connecting to host')

    parser.add_argument('-p', '--password',
                        required=False,
                        action='store',
                        help='Password to use when connecting to host')

    parser.add_argument('-vn', '--vm_name',
                        required=True,
                        action='store',
                        help='Name of virtual machine to perfom snapshot operation against')

    parser.add_argument('-so', '--snapshot_operation',
                        required=False,
                        action='store',
                        help='Snapshot operation (create/remove/revert/list_all/list_current/remove_all) that should be performed against specified VM (defaults to list_all)')

    parser.add_argument('-sn', '--snapshot_name',
                        required=False,
                        action='store',
                        help='Name of the VM Snapshot that the --snapshot_operation (create/remove/revert) should be performed against')

    parser.add_argument('-sd', '--snapshot_description',
                        required=False,
                        action='store',
                        help='Description of the VM Snapshot (useful when --snapshot_operation = create')

    parser.add_argument('-is', '--ignore_ssl',
                        required=False,
                        action='store',
                        help='Whether or not invalid SSL certficates should be ignored')

    parser.add_argument('-vb', '--verbose',
                        required=False,
                        action='store_true',
                        help='Show verbose output')

    args = parser.parse_args()

    if not args.password:
        args.password = getpass.getpass(
            prompt='Enter password for host %s and user %s: ' %
                   (args.host, args.user))
    return args



def get_obj(content, vimtype, name):
    """
     Get the vsphere object associated with a given text name
    """
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if c.name == name:
            obj = c
            break
    return obj


def list_snapshots_recursively(snapshots):
    snapshot_data = []
    snap_text = ""
    for snapshot in snapshots:
        snap_text = "Name: %s; Description: %s; CreateTime: %s; State: %s" % (
                                        snapshot.name, snapshot.description,
                                        snapshot.createTime, snapshot.state)
        snapshot_data.append(snap_text)
        snapshot_data = snapshot_data + list_snapshots_recursively(
                                        snapshot.childSnapshotList)
    return snapshot_data


def get_snapshots_by_name_recursively(snapshots, snapname):
    snap_obj = []
    for snapshot in snapshots:
        if snapshot.name == snapname:
            snap_obj.append(snapshot)
        else:
            snap_obj = snap_obj + get_snapshots_by_name_recursively(
                                    snapshot.childSnapshotList, snapname)
    return snap_obj


def get_current_snap_obj(snapshots, snapob):
    snap_obj = []
    for snapshot in snapshots:
        if snapshot.snapshot == snapob:
            snap_obj.append(snapshot)
        snap_obj = snap_obj + get_current_snap_obj(
                                snapshot.childSnapshotList, snapob)
    return snap_obj


def main():

    args = get_args()

    if args.verbose:
      verbose_on=True
    else:
      verbose_on=False

    if args.ignore_ssl:
      ignore_ssl=True
    else:
      ignore_ssl=False

    if args.snapshot_description:
      arg_snapshot_description=args.snapshot_description
    else:
      arg_snapshot_description='No snapshot description provided'

    si = None

    if verbose_on:
      print("Trying to connect to VCENTER SERVER . . .")

    context = None
    if ignore_ssl and hasattr(ssl, "_create_unverified_context"):
        context = ssl._create_unverified_context()

    try:
        si = connect.SmartConnect(host=args.host,
                                                user=args.user,
                                                pwd=args.password,
                                                port=int(args.port))

        atexit.register(connect.Disconnect, si)

        if verbose_on:
          print("Connected to vcenter server {}!".format(args.host))
          # NOTE (hartsock): only a successfully authenticated session has a
          # session key aka session id.
          session_id = si.content.sessionManager.currentSession.key
          print("current session id: {}".format(session_id))


    except vmodl.MethodFault as error:
        print("Caught vmodl fault : " + error.msg)
        return -1


    atexit.register(Disconnect, si)


    content = si.RetrieveContent()

    operation = args.snapshot_operation
    vm_name = args.vm_name
    arg_snapshot_name = args.snapshot_name

    vm = get_obj(content, [vim.VirtualMachine], vm_name)

    if not vm:
        print("Virtual Machine %s doesn't exists" % vm_name)
        sys.exit()

    if operation != 'create' and vm.snapshot is None:
        print("Virtual Machine %s doesn't have any snapshots" % vm.name)
        sys.exit()

    if operation == 'create':
        snapshot_name = arg_snapshot_name
        description = arg_snapshot_description
        dumpMemory = False
        quiesce = False

        print("Creating snapshot %s for virtual machine %s" % (
                                        snapshot_name, vm.name))
        WaitForTask(vm.CreateSnapshot(
            snapshot_name, description, dumpMemory, quiesce))

    elif operation in ['remove', 'revert']:
        snapshot_name = arg_snapshot_name
        snap_obj = get_snapshots_by_name_recursively(
                            vm.snapshot.rootSnapshotList, snapshot_name)
        # if len(snap_obj) is 0; then no snapshots with specified name
        if len(snap_obj) == 1:
            snap_obj = snap_obj[0].snapshot
            if operation == 'remove':
                print("Removing snapshot %s" % snapshot_name)
                WaitForTask(snap_obj.RemoveSnapshot_Task(True))
            else:
                print("Reverting to snapshot %s" % snapshot_name)
                WaitForTask(snap_obj.RevertToSnapshot_Task())
        else:
            print("No snapshots found with name: %s on VM: %s" % (
                                                snapshot_name, vm.name))

    elif operation == 'list_all':
        print("Display list of snapshots on virtual machine %s" % vm.name)
        snapshot_paths = list_snapshots_recursively(
                            vm.snapshot.rootSnapshotList)
        for snapshot in snapshot_paths:
            print(snapshot)

    elif operation == 'list_current':
        current_snapref = vm.snapshot.currentSnapshot
        current_snap_obj = get_current_snap_obj(
                            vm.snapshot.rootSnapshotList, current_snapref)
        current_snapshot = "Name: %s; Description: %s; " \
                           "CreateTime: %s; State: %s" % (
                                current_snap_obj[0].name,
                                current_snap_obj[0].description,
                                current_snap_obj[0].createTime,
                                current_snap_obj[0].state)
        print("Virtual machine %s current snapshot is:" % vm.name)
        print(current_snapshot)

    elif operation == 'remove_all':
        print("Removing all snapshots for virtual machine %s" % vm.name)
        WaitForTask(vm.RemoveAllSnapshots())

    else:
        print("Specify operation in "
              "create/remove/revert/list_all/list_current/remove_all")

    return 0

# Start program
if __name__ == "__main__":
    main()
