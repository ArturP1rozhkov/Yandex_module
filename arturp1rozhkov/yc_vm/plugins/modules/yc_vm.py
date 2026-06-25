#!/usr/bin/python3

import json
import shutil
import subprocess
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r'''
---
module: yc_vm
short_description: Manage Yandex Cloud VM instances
description:
  - Custom module for Yandex Cloud VM management.
options:
  name:
    description:
      - VM name.
    required: true
    type: str
  hostname:
    description:
      - Hostname inside VM.
    required: false
    type: str
  zone:
    description:
      - Availability zone.
    required: true
    type: str
  platform_id:
    description:
      - Yandex Cloud platform ID.
    required: true
    type: str
  cores:
    description:
      - Number of vCPUs.
    required: true
    type: int
  memory:
    description:
      - Memory size in GB.
    required: true
    type: int
  core_fraction:
    description:
      - CPU core fraction.
    required: false
    type: int
    default: 100
  image_family:
    description:
      - Image family name.
    required: true
    type: str
  subnet_id:
    description:
      - Subnet ID.
    required: true
    type: str
  nat:
    description:
      - Attach external IP.
    required: false
    type: bool
    default: true
  ssh_user:
    description:
      - SSH user name.
    required: true
    type: str
  public_key_path:
    description:
      - Path to SSH public key.
    required: true
    type: str
  state:
    description:
      - Desired existence state.
    required: false
    type: str
    choices: [present, absent]
    default: present
  vm_state:
    description:
      - Desired runtime state for an existing VM.
    required: false
    type: str
    choices: [running, stopped]
    default: running
author:
  - Artur Pirozhkov
'''


EXAMPLES = r'''
- name: Ensure VM exists and is running
  arturp1rozhkov.yc_vm.yc_vm:
    name: clickhouse-01
    hostname: clickhouse-01
    zone: ru-central1-a
    platform_id: standard-v3
    cores: 2
    memory: 4
    core_fraction: 20
    image_family: rocky-linux-9
    subnet_id: subnet-id
    nat: true
    ssh_user: rocky
    public_key_path: ~/.ssh/id_ed25519.pub
    state: present
    vm_state: running
'''


RETURN = r'''
changed:
  description: Whether the module changed anything.
  type: bool
  returned: always
vm:
  description: VM parameters received by the module.
  type: dict
  returned: always
message:
  description: Human-readable result.
  type: str
  returned: always
exists:
  description: Whether the instance exists.
  type: bool
  returned: always
current_status:
  description: Current VM status in Yandex Cloud.
  type: str
  returned: always
desired_action:
  description: Action determined by the module.
  type: str
  returned: always
instance_id:
  description: Yandex Cloud instance ID.
  type: str
  returned: when available
fqdn:
  description: Internal FQDN of the instance.
  type: str
  returned: when available
internal_ip:
  description: Internal IPv4 address.
  type: str
  returned: when available
public_ip:
  description: Public IPv4 NAT address.
  type: str
  returned: when available
'''


def list_instances(module, yc_cli_path):
    list_cmd = [yc_cli_path, "compute", "instance", "list", "--format", "json"]

    try:
        proc = subprocess.run(
            list_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        module.fail_json(
            msg="yc CLI command failed",
            changed=False,
            stderr=e.stderr,
            stdout=e.stdout,
            return_code=e.returncode,
            command=" ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd),
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        module.fail_json(
            msg="failed to parse yc CLI JSON output",
            changed=False,
            error=str(e),
            raw_stdout=proc.stdout,
        )


def find_instance_by_name(instances, name):
    for instance in instances:
        if instance.get("name") == name:
            return instance
    return None


def extract_instance_facts(instance):
    if not instance:
        return {
            "instance_id": None,
            "fqdn": None,
            "internal_ip": None,
            "public_ip": None,
        }

    instance_id = instance.get("id")
    fqdn = instance.get("fqdn")
    internal_ip = None
    public_ip = None

    network_interfaces = instance.get("network_interfaces", [])
    if network_interfaces:
        primary_v4 = network_interfaces[0].get("primary_v4_address", {})
        internal_ip = primary_v4.get("address")

        one_to_one_nat = primary_v4.get("one_to_one_nat", {})
        public_ip = one_to_one_nat.get("address")

    return {
        "instance_id": instance_id,
        "fqdn": fqdn,
        "internal_ip": internal_ip,
        "public_ip": public_ip,
    }


def run_module():
    module_args = dict(
        name=dict(type='str', required=True),
        hostname=dict(type='str', required=False, default=None),
        zone=dict(type='str', required=True),
        platform_id=dict(type='str', required=True),
        cores=dict(type='int', required=True),
        memory=dict(type='int', required=True),
        core_fraction=dict(type='int', required=False, default=100),
        image_family=dict(type='str', required=True),
        subnet_id=dict(type='str', required=True),
        nat=dict(type='bool', required=False, default=True),
        ssh_user=dict(type='str', required=True),
        public_key_path=dict(type='str', required=True),
        state=dict(type='str', required=False, default='present', choices=['present', 'absent']),
        vm_state=dict(type='str', required=False, default='running', choices=['running', 'stopped']),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
    )

    try:
        params = module.params.copy()
        yc_cli_path = shutil.which("yc")

        if yc_cli_path is None:
            module.fail_json(
                msg="yc CLI not found in PATH",
                changed=False,
            )

        instances = list_instances(module, yc_cli_path)
        matched_instance = find_instance_by_name(instances, params["name"])
        instance_facts = extract_instance_facts(matched_instance)

        exists = matched_instance is not None
        current_status = matched_instance.get("status") if matched_instance else None
        desired_action = "none"

        if params["state"] == "absent":
            would_change = exists
            if exists:
                desired_action = "delete"
        else:
            if not exists:
                would_change = True
                desired_action = "create"
            else:
                if params["vm_state"] == "running" and current_status != "RUNNING":
                    would_change = True
                    desired_action = "start"
                elif params["vm_state"] == "stopped" and current_status != "STOPPED":
                    would_change = True
                    desired_action = "stop"
                else:
                    would_change = False

        result = dict(
            changed=False,
            message="yc_vm checked instance state successfully",
            vm=params,
            exists=exists,
            current_status=current_status,
            would_change=would_change,
            desired_action=desired_action,
            cli_found=True,
            yc_cli_path=yc_cli_path,
            matched_instance=matched_instance,
            instance_id=instance_facts["instance_id"],
            fqdn=instance_facts["fqdn"],
            internal_ip=instance_facts["internal_ip"],
            public_ip=instance_facts["public_ip"],
        )

        if module.check_mode:
            result["changed"] = would_change
            result["message"] = "check mode: no changes applied"
            module.exit_json(**result)

        if desired_action == "start":
            start_target = matched_instance["id"]
            start_cmd = [yc_cli_path, "compute", "instance", "start", start_target]

            try:
                start_proc = subprocess.run(
                    start_cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                module.fail_json(
                    msg="failed to start instance",
                    changed=False,
                    stderr=e.stderr,
                    stdout=e.stdout,
                    return_code=e.returncode,
                    command=" ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd),
                )

            refreshed_instances = list_instances(module, yc_cli_path)
            refreshed_instance = find_instance_by_name(refreshed_instances, params["name"])
            refreshed_instance_facts = extract_instance_facts(refreshed_instance)

            result["changed"] = True
            result["message"] = "instance started successfully"
            result["start_command"] = " ".join(start_cmd)
            result["start_stdout"] = start_proc.stdout
            result["start_stderr"] = start_proc.stderr
            result["matched_instance"] = refreshed_instance
            result["current_status"] = refreshed_instance.get("status") if refreshed_instance else current_status
            result["instance_id"] = refreshed_instance_facts["instance_id"]
            result["fqdn"] = refreshed_instance_facts["fqdn"]
            result["internal_ip"] = refreshed_instance_facts["internal_ip"]
            result["public_ip"] = refreshed_instance_facts["public_ip"]

            if result["current_status"] == "RUNNING":
                result["desired_action"] = "none"
                result["would_change"] = False
            else:
                result["would_change"] = True

            module.exit_json(**result)

        result["message"] = "no changes required"
        module.exit_json(**result)

    except Exception as e:
        module.fail_json(
            msg="unexpected module error",
            changed=False,
            error=str(e),
        )


def main():
    run_module()


if __name__ == '__main__':
    main()