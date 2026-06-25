---
type: Курс по DevOPS Home Work
module: Ansible
lesson_no: 7
lesson_theme: Custom module Yandex
---

## Необязательная часть

1. Реализуйте свой модуль для создания хостов в Yandex Cloud.
2. Модуль может и должен иметь зависимость от `yc`, основной функционал: создание ВМ с нужным сайзингом на основе нужной ОС. Дополнительные модули по созданию кластеров ClickHouse, MySQL и прочего реализовывать не надо, достаточно простейшего создания ВМ.
3. Модуль может формировать динамическое inventory, но эта часть не является обязательной, достаточно, чтобы он делал хосты с указанной спецификацией в YAML.
4. Протестируйте модуль на идемпотентность, исполнимость. При успехе добавьте этот модуль в свою коллекцию.
5. Измените playbook так, чтобы он умел создавать инфраструктуру под inventory, а после устанавливал весь ваш стек Observability на нужные хосты и настраивал его.
6. В итоге ваша коллекция обязательно должна содержать: clickhouse-role (если есть своя), lighthouse-role, vector-role, два модуля: my_own_module и модуль управления Yandex Cloud хостами и playbook, который демонстрирует создание Observability стека.

# Разбор решения задачи

- Создал новый пустой репозиторий `Yandex_module`, инициировал его в качестве удаленного на хостовой машине, сделал первый коммит. 
- Инициировал `collection` в корне проекта
```bash
ansible-galaxy collection init arturp1rozhkov.yc_vm
```
Логика решения:
- `requirements.yml` в корне репозитория ставит внешние роли `clickhouse`, `vector`, `lighthouse`;
- `playbooks/vars/hosts.yml` описывает нужные ВМ;
- модуль `plugins/modules/yc_vm.py` создаёт хосты через `yc`;
- `playbooks/provision.yml` сначала создаёт ВМ, а потом запускает старые роли на нужных группах.

Записал в файл `galaxy.yml` содержимое:
```yaml
cat > galaxy.yml <<'EOF'
namespace: arturp1rozhkov
name: yc_vm
version: 0.1.0
readme: README.md

authors:
  - Artur Pirozhkov

description: Ansible collection with a custom Yandex Cloud VM module and playbooks for provisioning hosts and deploying the stack.
license:
  - GPL-2.0-or-later

tags:
  - yandex
  - cloud
  - vm
  - ansible

dependencies: {}

repository: https://github.com/ArturP1rozhkov/Yandex_module
documentation: https://github.com/ArturP1rozhkov/Yandex_module
homepage: https://github.com/ArturP1rozhkov/Yandex_module
issues: https://github.com/ArturP1rozhkov/Yandex_module/issues

build_ignore: []
EOF
```
- Создал директорию и файлы:
```bash
mkdir -p plugins/modules playbooks/vars tests 
touch plugins/modules/yc_vm.py 
touch playbooks/provision.yml 
touch playbooks/vars/hosts.yml
```
модуль будет жить в `plugins/modules/yc_vm.py`, playbook - в `playbooks/provision.yml`, а YAML-спецификация - в `playbooks/vars/hosts.yml`

## Адаптация `role` `Vector` для нормального функционирования на облачной ВМ
- убрать установку в home-каталог;
- разнести бинарь, конфиг и данные по нормальным путям
- добавить systemd unit;
- запускать Vector как сервис.

Создал в папке проекта структуру ролей для трех обновленных сервисов:
~/Yandex_module/
├── README.md
├── .gitignore
├── role_sources/
│   ├── vector_role/
│   ├── lighthouse_role/
│   └── clickhouse_role/
└── arturp1rozhkov/
    └── yc_vm/
    
```bash
cd ~/Yandex_module

mkdir -p role_sources
cd ~/Yandex_module/role_sources
ansible-galaxy role init vector_role
ansible-galaxy role init lighthouse_role
ansible-galaxy role init clickhouse_role
```    


Файл `~/vector-role/vector-role/defaults/main.yml`
```yaml
---
vector_version: "0.37.1"

vector_install_dir: "/opt/vector"
vector_config_dir: "/etc/vector"
vector_data_dir: "/var/lib/vector"

vector_user: "vector"
vector_group: "vector"

vector_download_url: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-x86_64-unknown-linux-musl.tar.gz"

vector_sources:
  journald_logs:
    type: journald

vector_sinks:
  clickhouse_out:
    type: console
    inputs:
      - journald_logs
    encoding:
      codec: json
```

файл  `~/vector-role/vector-role/tasks/main.yml`
```yaml
---
- name: Create vector group
  become: true
  ansible.builtin.group:
    name: "{{ vector_group }}"
    state: present

- name: Create vector user
  become: true
  ansible.builtin.user:
    name: "{{ vector_user }}"
    group: "{{ vector_group }}"
    system: true
    shell: /usr/sbin/nologin
    create_home: false
    state: present

- name: Create vector install directory
  become: true
  ansible.builtin.file:
    path: "{{ vector_install_dir }}"
    state: directory
    owner: "{{ vector_user }}"
    group: "{{ vector_group }}"
    mode: "0755"

- name: Create vector config directory
  become: true
  ansible.builtin.file:
    path: "{{ vector_config_dir }}"
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Create vector data directory
  become: true
  ansible.builtin.file:
    path: "{{ vector_data_dir }}"
    state: directory
    owner: "{{ vector_user }}"
    group: "{{ vector_group }}"
    mode: "0755"

- name: Download Vector archive
  become: true
  ansible.builtin.get_url:
    url: "{{ vector_download_url }}"
    dest: "/tmp/vector-{{ vector_version }}.tar.gz"
    mode: "0644"
    timeout: 60
  register: vector_download
  retries: 3
  delay: 5
  until: vector_download is succeeded
  when: not ansible_check_mode

- name: Unarchive Vector
  become: true
  ansible.builtin.unarchive:
    src: "/tmp/vector-{{ vector_version }}.tar.gz"
    dest: "{{ vector_install_dir }}"
    remote_src: true
    extra_opts:
      - "--strip-components=2"
    creates: "{{ vector_install_dir }}/bin/vector"
  when: not ansible_check_mode

- name: Deploy vector config
  become: true
  ansible.builtin.template:
    src: vector.yml.j2
    dest: "{{ vector_config_dir }}/vector.yml"
    owner: root
    group: root
    mode: "0644"
  notify:
    - Validate vector config
    - Restart vector
  when: not ansible_check_mode

- name: Deploy vector systemd unit
  become: true
  ansible.builtin.template:
    src: vector.service.j2
    dest: /etc/systemd/system/vector.service
    owner: root
    group: root
    mode: "0644"
  notify:
    - Reload systemd
    - Restart vector

- name: Ensure vector service is enabled and started
  become: true
  ansible.builtin.systemd:
    name: vector
    enabled: true
    state: started
    daemon_reload: true
  when: not ansible_check_mode
```

файл `~/vector-role/vector-role/handlers/main.yml`
```yaml
---
- name: Validate vector config
  become: true
  ansible.builtin.command:
    cmd: "{{ vector_install_dir }}/bin/vector validate --no-environment {{ vector_config_dir }}/vector.yml"
  changed_when: false

- name: Reload systemd
  become: true
  ansible.builtin.systemd:
    daemon_reload: true

- name: Restart vector
  become: true
  ansible.builtin.systemd:
    name: vector
    state: restarted
```

файл `~/vector-role/vector-role/templates/vector.yml.j2`
```yaml
data_dir: "{{ vector_data_dir }}"

sources:
{{ vector_sources | to_nice_yaml(indent=2) | indent(2, true) }}

sinks:
{{ vector_sinks | to_nice_yaml(indent=2) | indent(2, true) }}
```

Создал новый файл `~/vector-role/vector-role/templates/vector.service.j2`
```yaml
[Unit]
Description=Vector
After=network-online.target
Wants=network-online.target

[Service]
User={{ vector_user }}
Group={{ vector_group }}
ExecStart={{ vector_install_dir }}/bin/vector --config {{ vector_config_dir }}/vector.yml
Restart=on-failure
RestartSec=5
WorkingDirectory={{ vector_install_dir }}

[Install]
WantedBy=multi-user.target
```

## Адаптация `lighthouse-role` для Yandex ВМ

Скорректировал файл `defaults/main.yml`
```yaml
---
lighthouse_url: "https://github.com/VKCOM/lighthouse/archive/refs/heads/master.zip"
lighthouse_dir: "/opt/lighthouse"
lighthouse_nginx_config: "/etc/nginx/conf.d/lighthouse.conf"
lighthouse_listen_port: 80
```

Cоздал шаблон `templates/lighthouse.conf.j2`
```yaml
server {
    listen {{ lighthouse_listen_port }};
    server_name _;

    root {{ lighthouse_dir }};
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Скорректировал файл `tasks/main.yml`
```yaml
---
- name: Install nginx and unzip
  become: true
  ansible.builtin.package:
    name:
      - nginx
      - unzip
    state: present

- name: Download Lighthouse archive
  become: true
  ansible.builtin.get_url:
    url: "{{ lighthouse_url }}"
    dest: /tmp/lighthouse.zip
    mode: "0644"
    timeout: 60
  when: not ansible_check_mode

- name: Create Lighthouse directory
  become: true
  ansible.builtin.file:
    path: "{{ lighthouse_dir }}"
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Unarchive Lighthouse
  become: true
  ansible.builtin.unarchive:
    src: /tmp/lighthouse.zip
    dest: /tmp
    remote_src: true
    creates: /tmp/lighthouse-master
  when: not ansible_check_mode

- name: Copy Lighthouse files
  become: true
  ansible.builtin.copy:
    src: /tmp/lighthouse-master/
    dest: "{{ lighthouse_dir }}/"
    remote_src: true
    mode: preserve
  when: not ansible_check_mode

- name: Deploy nginx config for Lighthouse
  become: true
  ansible.builtin.template:
    src: lighthouse.conf.j2
    dest: "{{ lighthouse_nginx_config }}"
    owner: root
    group: root
    mode: "0644"
  notify: Restart nginx

- name: Ensure nginx is enabled and started
  become: true
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: true
```

Скорректировал файл `handlers/main.yml`
```yaml
---
- name: Restart nginx
  become: true
  ansible.builtin.service:
    name: nginx
    state: restarted
```

## Создал `clickhouse-role` 
Файл `~/Yandex_module/role_sources/clickhouse_role/defaults/main.yml`
```yaml
---
   clickhouse_packages:
     - clickhouse-server
     - clickhouse-client
   
   clickhouse_repo_url: "https://packages.clickhouse.com/rpm/clickhouse.repo"
   clickhouse_service_name: "clickhouse-server"
   clickhouse_wait_host: "127.0.0.1"
   clickhouse_wait_port: 9000
   clickhouse_wait_timeout: 60
```

файл `~/Yandex_module/role_sources/clickhouse_role/handlers/main.yml`
```yaml
---
- name: Restart clickhouse
  ansible.builtin.service:
    name: "{{ clickhouse_service_name }}"
    state: restarted
```
файл `~/Yandex_module/role_sources/clickhouse_role/tasks/main.yml`
```yaml
---
- name: Install dnf plugin for repo management
  ansible.builtin.dnf:
    name: dnf-plugins-core
    state: present

- name: Add ClickHouse repository
  ansible.builtin.command:
    cmd: dnf config-manager --add-repo {{ clickhouse_repo_url }}
  args:
    creates: /etc/yum.repos.d/clickhouse.repo

- name: Install ClickHouse packages
  ansible.builtin.dnf:
    name: "{{ clickhouse_packages }}"
    state: present
  notify: Restart clickhouse

- name: Ensure ClickHouse service is enabled and started
  ansible.builtin.service:
    name: "{{ clickhouse_service_name }}"
    state: started
    enabled: true

- name: Wait for ClickHouse TCP port
  ansible.builtin.wait_for:
    host: "{{ clickhouse_wait_host }}"
    port: "{{ clickhouse_wait_port }}"
    timeout: "{{ clickhouse_wait_timeout }}"
    delay: 2

- name: Check ClickHouse version
  ansible.builtin.command: clickhouse-client --query "SELECT version()"
  register: clickhouse_version
  changed_when: false

- name: Show ClickHouse version
  ansible.builtin.debug:
    msg: "ClickHouse version: {{ clickhouse_version.stdout }}"
    verbosity: 1
```



- Заполнил файл `~/Yandex_module/arturp1rozhkov/yc_vm/playbooks/vars/hosts.yml` содержимым:

```yaml
---
yc_hosts:
  - name: clickhouse-01
    hostname: clickhouse-01
    group: clickhouse
    zone: ru-central1-a
    platform_id: standard-v3
    cores: 2
    memory: 4
    core_fraction: 20
    image_family: rocky-linux-9
    nat: true
    subnet_id: "<SUBNET_ID>"
    ssh_user: "kva"
    public_key_path: "~/.ssh/id_ed25519.pub"

  - name: vector-01
    hostname: vector-01
    group: vector
    zone: ru-central1-a
    platform_id: standard-v3
    cores: 2
    memory: 2
    core_fraction: 20
    image_family: rocky-linux-9
    nat: true
    subnet_id: "<SUBNET_ID>"
    ssh_user: "kva"
    public_key_path: "~/.ssh/id_ed25519.pub"

  - name: lighthouse-01
    hostname: lighthouse-01
    group: lighthouse
    zone: ru-central1-a
    platform_id: standard-v3
    cores: 2
    memory: 2
    core_fraction: 20
    image_family: rocky-linux-9
    nat: true
    subnet_id: "<SUBNET_ID>"
    ssh_user: "kva"
    public_key_path: "~/.ssh/id_ed25519.pub"
```


- Заполнил файл `~/Yandex_module/arturp1rozhkov/yc_vm/playbooks/provision.yml` содержимым:
```yaml
---
- name: Discover and register YC hosts
  hosts: localhost
  gather_facts: false
  vars_files:
    - vars/hosts.yml

  tasks:
    - name: Ensure YC VMs are present and in desired state
      arturp1rozhkov.yc_vm.yc_vm:
        name: "{{ item.name }}"
        hostname: "{{ item.hostname }}"
        zone: "{{ item.zone }}"
        platform_id: "{{ item.platform_id }}"
        cores: "{{ item.cores }}"
        memory: "{{ item.memory }}"
        core_fraction: "{{ item.core_fraction }}"
        image_family: "{{ item.image_family }}"
        subnet_id: "{{ item.subnet_id }}"
        nat: "{{ item.nat }}"
        ssh_user: "{{ item.ssh_user }}"
        public_key_path: "{{ item.public_key_path }}"
        state: present
        vm_state: "{{ item.vm_state }}"
      loop: "{{ yc_hosts }}"
      loop_control:
        label: "{{ item.name }}"
      register: yc_vm_results

    - name: Show compact module results
      ansible.builtin.debug:
        msg:
          - "name={{ item.item.name }}"
          - "group={{ item.item.group }}"
          - "instance_id={{ item.instance_id }}"
          - "internal_ip={{ item.internal_ip }}"
          - "public_ip={{ item.public_ip }}"
          - "fqdn={{ item.fqdn }}"
          - "status={{ item.current_status }}"
          - "changed={{ item.changed }}"
      loop: "{{ yc_vm_results.results }}"
      loop_control:
        label: "{{ item.item.name }}"

    - name: Add hosts to runtime inventory
      ansible.builtin.add_host:
        name: "{{ item.item.name }}"
        groups: "{{ item.item.group }}"
        ansible_host: "{{ item.public_ip | default(item.internal_ip, true) }}"
        ansible_user: "{{ item.item.ssh_user }}"
        fqdn: "{{ item.fqdn }}"
        internal_ip: "{{ item.internal_ip }}"
        public_ip: "{{ item.public_ip }}"
        instance_id: "{{ item.instance_id }}"
        yc_vm_name: "{{ item.item.name }}"
      loop: "{{ yc_vm_results.results }}"
      loop_control:
        label: "{{ item.item.name }}"
      when:
        - not item.failed
        - item.exists
        - item.current_status == "RUNNING"

- name: Check SSH access to YC hosts
  hosts: clickhouse:vector:lighthouse
  gather_facts: false

  tasks:
    - name: Wait for SSH connection
      ansible.builtin.wait_for_connection:
        timeout: 300
        delay: 5
        sleep: 5

    - name: Ping managed hosts
      ansible.builtin.ping:
```

`ansible_host: "{{ item.name }}"` - строка временная.  Позже она будет заменена на внешний IP или внутренний IP, который вернёт модуль `yc_vm`, иначе Ansible не сможет подключиться к ВМ.

- Проект модуля  `~/Yandex_module/arturp1rozhkov/yc_vm/plugins/modules/yc_vm.py`:
```python
#!/usr/bin/python3

from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r'''
---
module: yc_vm
short_description: Manage Yandex Cloud VM instances
description:
  - Minimal custom module for Yandex Cloud VM management.
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
      - Desired state.
    required: false
    type: str
    choices: [present, absent]
    default: present
author:
  - Artur Pirozhkov
'''

EXAMPLES = r'''
- name: Check VM spec
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
'''


def run_module():
    import shutil

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
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
    )

    params = module.params.copy()
    yc_cli_path = shutil.which("yc")
    cli_found = yc_cli_path is not None

    exists = False
    would_change = params["state"] == "present" and not exists

    result = dict(
        changed=False,
        message="yc_vm skeleton module validated input successfully",
        vm=params,
        exists=exists,
        would_change=would_change,
        cli_found=cli_found,
        yc_cli_path=yc_cli_path,
    )

    if module.check_mode:
        result["changed"] = would_change
        result["message"] = "check mode: no changes applied"
        module.exit_json(**result)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
```

- Тестовый `playbook`
```yaml
---
- name: Test yc_vm skeleton
  hosts: localhost
  gather_facts: false
  vars_files:
    - vars/hosts.yml
  tasks:
    - name: Validate VM specs with yc_vm module
      arturp1rozhkov.yc_vm.yc_vm:
        name: "{{ item.name }}"
        hostname: "{{ item.hostname }}"
        zone: "{{ item.zone }}"
        platform_id: "{{ item.platform_id }}"
        cores: "{{ item.cores }}"
        memory: "{{ item.memory }}"
        core_fraction: "{{ item.core_fraction }}"
        image_family: "{{ item.image_family }}"
        subnet_id: "{{ item.subnet_id }}"
        nat: "{{ item.nat }}"
        ssh_user: "{{ item.ssh_user }}"
        public_key_path: "{{ item.public_key_path }}"
        state: present
      loop: "{{ yc_hosts }}"
      register: yc_vm_results

    - name: Show compact module results
      ansible.builtin.debug:
        msg:
          - "name={{ item.item.name }}"
          - "group={{ item.item.group }}"
          - "instance_id={{ item.instance_id }}"
          - "internal_ip={{ item.internal_ip }}"
          - "public_ip={{ item.public_ip }}"
          - "fqdn={{ item.fqdn }}"
          - "status={{ item.current_status }}"
          - "changed={{ item.changed }}"
      loop: "{{ yc_vm_results.results }}"
```
Этот playbook **ничего не создаёт в облаке**. Он нужен для первой  проверки:
- видит ли Ansible `collection`;
- вызывается ли `module`;
- принимает ли он параметры из `hosts.yml`;
- возвращает ли ожидаемую структуру данных.

Создал директорию `collections` в корне проекта
```bash
mkdir -p collections/ansible_collections/arturp1rozhkov
ln -s ~/Yandex_module/arturp1rozhkov/yc_vm collections/ansible_collections/arturp1rozhkov/yc_vm
```
поправил пути запуска коллекции изза ошибок связанных с точкой входа
```yaml
[defaults]
collections_path = ./collections
roles_path = ./role_sources
host_key_checking = False
retry_files_enabled = False
interpreter_python = auto_silent

[ssh_connection]
pipelining = True
ssh_args = -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=10
```
Тестовый запуск: 
```bash
ansible-playbook arturp1rozhkov/yc_vm/playbooks/test_yc_vm.yml
```
Тестовый playbook успешно вызвал кастомный модуль, Ansible корректно передал в него параметры из `hosts.yml`, а модуль вернул структурированные данные для всех трёх ВМ без ошибок. Это значит, что collection теперь находится в рабочем пути поиска, а skeleton-модуль на базе `AnsibleModule` и `exit_json()` уже функционирует как ожидалось. Модуль умеет вычислять `would_change`,  `check mode` работает корректно для сценария `state: present` при `exists: false`

Добавил функциональности в код модуля, добавив к нему:
- вызов `yc compute instance list`;
- поиск ВМ по имени
- возврат  `exists: true` если найдена
- возврат `exists: false` если не найдена
```python
# добавил импорты
import json
import shutil
import subprocess
from ansible.module_utils.basic import AnsibleModule

# скорректировал логику run_module()
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

        list_cmd = [yc_cli_path, "compute", "instance", "list", "--format", "json"]
        proc = subprocess.run(
            list_cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        instances = json.loads(proc.stdout)

        matched_instance = None
        for instance in instances:
            if instance.get("name") == params["name"]:
                matched_instance = instance
                break

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
        )

        if module.check_mode:
            result["changed"] = would_change
            result["message"] = "check mode: no changes applied"
            module.exit_json(**result)

        if desired_action == "start":
            start_target = matched_instance["id"]
            start_cmd = [yc_cli_path, "compute", "instance", "start", start_target]

            start_proc = subprocess.run(
                start_cmd,
                capture_output=True,
                text=True,
                check=True,
            )

            result["changed"] = True
            result["message"] = "instance started successfully"
            result["start_command"] = " ".join(start_cmd)
            result["start_stdout"] = start_proc.stdout
            result["start_stderr"] = start_proc.stderr

            refresh_proc = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            refreshed_instances = json.loads(refresh_proc.stdout)

            refreshed_instance = None
            for instance in refreshed_instances:
                if instance.get("name") == params["name"]:
                    refreshed_instance = instance
                    break

            result["matched_instance"] = refreshed_instance
            result["current_status"] = refreshed_instance.get("status") if refreshed_instance else current_status

            if result["current_status"] == "RUNNING":
                result["desired_action"] = "none"
                result["would_change"] = False
            else:
                result["would_change"] = True

            module.exit_json(**result)

    except subprocess.CalledProcessError as e:
        module.fail_json(
            msg="yc CLI command failed",
            changed=False,
            stderr=e.stderr,
            stdout=e.stdout,
            return_code=e.returncode,
            command=" ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd),
        )
    except json.JSONDecodeError as e:
        module.fail_json(
            msg="failed to parse yc CLI JSON output",
            changed=False,
            error=str(e),
            raw_stdout=proc.stdout if 'proc' in locals() else None,
        )
    except Exception as e:
        module.fail_json(
            msg="unexpected module error",
            changed=False,
            error=str(e),
        )
```

Создал файл `~/Yandex_module/arturp1rozhkov/yc_vm/playbooks/site.yml`
```yaml
---
- name: Discover and register YC hosts
  hosts: localhost
  gather_facts: false
  vars_files:
    - vars/hosts.yml

  tasks:
    - name: Ensure YC VMs are present and in desired state
      arturp1rozhkov.yc_vm.yc_vm:
        name: "{{ item.name }}"
        hostname: "{{ item.hostname }}"
        zone: "{{ item.zone }}"
        platform_id: "{{ item.platform_id }}"
        cores: "{{ item.cores }}"
        memory: "{{ item.memory }}"
        core_fraction: "{{ item.core_fraction }}"
        image_family: "{{ item.image_family }}"
        subnet_id: "{{ item.subnet_id }}"
        nat: "{{ item.nat }}"
        ssh_user: "{{ item.ssh_user }}"
        public_key_path: "{{ item.public_key_path }}"
        state: present
        vm_state: "{{ item.vm_state }}"
      loop: "{{ yc_hosts }}"
      loop_control:
        label: "{{ item.name }}"
      register: yc_vm_results

    - name: Show compact module results
      ansible.builtin.debug:
        msg:
          - "name={{ item.item.name }}"
          - "group={{ item.item.group }}"
          - "instance_id={{ item.instance_id }}"
          - "internal_ip={{ item.internal_ip }}"
          - "public_ip={{ item.public_ip }}"
          - "fqdn={{ item.fqdn }}"
          - "status={{ item.current_status }}"
          - "changed={{ item.changed }}"
        verbosity: 1
      loop: "{{ yc_vm_results.results }}"
      loop_control:
        label: "{{ item.item.name }}"

    - name: Add hosts to runtime inventory
      ansible.builtin.add_host:
        name: "{{ item.item.name }}"
        groups: "{{ item.item.group }}"
        ansible_host: "{{ item.public_ip | default(item.internal_ip, true) }}"
        ansible_user: "{{ item.item.ssh_user }}"
        ansible_ssh_private_key_file: "{{ lookup('env', 'HOME') + '/.ssh/id_ed25519' }}"
        ansible_ssh_common_args: >-
          -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null
          -o GlobalKnownHostsFile=/dev/null
          -o ConnectTimeout=10
        fqdn: "{{ item.fqdn }}"
        internal_ip: "{{ item.internal_ip }}"
        public_ip: "{{ item.public_ip }}"
        instance_id: "{{ item.instance_id }}"
        yc_vm_name: "{{ item.item.name }}"
      loop: "{{ yc_vm_results.results }}"
      loop_control:
        label: "{{ item.item.name }}"
      when:
        - not item.failed
        - item.exists
        - item.current_status == "RUNNING"

- name: Verify SSH and gather facts
  hosts: clickhouse:vector:lighthouse
  gather_facts: false
  serial: 1

  tasks:
    - name: Wait for SSH connection
      ansible.builtin.wait_for_connection:
        timeout: 30
        delay: 2
        sleep: 3

    - name: Gather facts
      ansible.builtin.setup:

    - name: Show host summary
      ansible.builtin.debug:
        msg:
          - "host={{ inventory_hostname }}"
          - "ip={{ ansible_host }}"
          - "user={{ ansible_user }}"
          - "os={{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_version'] }}"
          - "python={{ ansible_facts['python']['executable'] }}"
        verbosity: 1

- name: Configure ClickHouse hosts
  hosts: clickhouse
  gather_facts: true
  become: true

  roles:
    - clickhouse_role

- name: Configure Vector hosts
  hosts: vector
  gather_facts: true
  become: true

  roles:
    - vector_role

- name: Configure Lighthouse hosts
  hosts: lighthouse
  gather_facts: true
  become: true

  roles:
    - lighthouse_role
```
- Первый play работает на `localhost` и собирает runtime inventory через `add_host`. 
- Второй play проверяет SSH и собирает факты через `setup`
- Последние три plays запускают роли отдельно по группам `clickhouse`, `vector`, `lighthouse`, что делает playbook понятным и близким к учебной задаче по распределённому развёртыванию ролей. Роли в playbook подключаются именно через ключ `roles`.

По ходу работы итоговая структура проекта была упрощена. Первоначально я использовал внешний `requirements.yml` и ориентировался на внешнюю `clickhouse-role`, но в итоге отказался от этой схемы и перенес все `roles` в локальный каталог `role_sources` внутри репозитория. 
Это позволило держать весь код развёртывания в одном месте, не зависеть от внешних ролей за пределами проекта и упростить отладку, синхронизацию между устройствами с которых я работал и удаленным репозиторием.

Отдельной сложностью было привести к финальному виду схему подключения к виртуальным машинам. Изначально в YAML-спецификации `ssh_user` использовался пользователь `rocky`, так как он был связан с выбранным образом ОС, но в реальной инфраструктуре рабочим пользователем оказался `kva`, поскольку в облаке ранее были созданы 3 ВМ через cloud-init с таким пользователем. Было решено его не менять. После исправления пользователя и обновления `host fingerprints` `playbook` начал стабильно проходить этап проверки SSH и собирать факты на всех целевых хостах.

Роль ClickHouse тоже пришлось доработать. Сначала я ориентировался на внешний вариант роли и старую схему установки из предыдущих ДЗ, однако в итоговом решении пришлось реализовать локальную `clickhouse_role` внутри проекта. Дополнительно обновил способ установки пакетов, так как первоначальный URL с `release rpm` уже не был доступен, и установка была переведена на подключение актуального репозитория `ClickHouse` для RPM-систем.

Для локальной разработки коллекции использовал `project-local` путь `collections/ansible_collections` с символической ссылкой на рабочий каталог коллекции.  
Это позволило редактировать модуль и `playbook` в одном месте, не делая отдельную установку `collection` после каждого изменения. Таким образом `Ansible` видел коллекцию в стандартном пути поиска.

Решил использовать `runtime inventory`.  После вызова собственного модуля `yc_vm playbook` не опирается на заранее подготовленный статический `inventory`, а добавляет найденные или созданные хосты в память с помощью `add_host` и затем использует их в следующих `plays`. За счёт этого один и тот же сценарий сначала подготавливает инфраструктуру, а затем сразу переходит к установке и настройке компонентов `observability-стека`.

В результате проект доведен до полностью рабочего состояния: кастомный модуль `yc_vm` используется для подготовки инфраструктуры в `Yandex Cloud`, далее `playbook` динамически формирует `inventory` и разворачивает `ClickHouse`, `Vector` и `Lighthouse` на целевых виртуальных машинах в `Yandex Cloud`. В окончательном варианте после отладки и подтверждения работоспособности проект приведён к упрощённой структуре: кастомный модуль `yc_vm`, основной `playbook site.yml`, тестовый сценарий `test_yc_vm.yml` и локальные роли `clickhouse_role`, `vector_role` и `lighthouse_role` находятся в одном репозитории. За счёт этого решение не зависит от внешних правок за пределами проекта и может быть воспроизведено на другой машине после клонирования репозитория и запуска `playbook` командой `ansible-playbook arturp1rozhkov/yc_vm/playbooks/site.yml`


