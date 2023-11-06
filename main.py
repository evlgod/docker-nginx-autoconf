from jinja2 import Environment, FileSystemLoader
from asyncio import run, create_task
from os import system, remove, path
from sys import exit
import docker


class Colors:
    head = '\033[95m'
    blue = '\033[94m'
    cyan = '\033[96m'
    green = '\033[92m'
    warn = '\033[93m'
    fail = '\033[91m'
    end = '\033[0m'
    bold = '\033[1m'
    underline = '\033[4m'


# if permission error - chmod 666 /var/run/docker.sock
# client = docker.Client(base_url='unix://var/run/docker.sock')
client = docker.from_env()
nginx_config_dir = '/etc/nginx/conf.d'  # folder with nginx config files
# {'name': container}
container_filter = {'label': 'app.virtual_host'}  # search containers by filter
# container_find_time = 5  # wait before searching for running containers
container_statuses = ['running', 'exited', 'removing']  # 'restarting'


async def get_port(container) -> str:
    """ get container port """
    ports = container.ports
    port = str()
    for key, val in ports.items():
        port = key.split('/')[0] if '/' in key else key
        break
    return port


async def get_ip_addr(container) -> str:
    """ get container ip address """
    net = container.attrs['NetworkSettings']
    addr = container.attrs['NetworkSettings']['IPAddress']
    if not addr:  # docker compose
        for key, val in net['Networks'].items():
            addr = val['IPAddress']
            break
    return addr


async def read_nginx_conf(name) -> str:
    """ reads a config file for the container """
    print('> read config')  # debug
    conf = f'{nginx_config_dir}/{name}.conf'
    if path.isfile(conf):
        with open(conf, 'r') as f:
            return f.read()
    return ''


async def write_nginx_conf(name, data) -> None:
    """ writes a config file for the container """
    print('> write config')  # debug
    conf = f'{nginx_config_dir}/{name}.conf'
    with open(conf, 'w') as f:
        f.write(data)


async def remove_nginx_conf(container) -> None:
    """ removes a config file for the container """
    print('> remove config')  # debug
    conf = f'{nginx_config_dir}/{container.name}.conf'
    if path.isfile(conf):
        remove(conf)


async def create_nginx_conf(container) -> None:
    """ creates a config file for the container """
    print('> create config')  # debug
    name = container.name
    addr = await get_ip_addr(container)
    port = await get_port(container)

    cont = {'server_name': name,
            'server_port': port,
            'upstreams': f'server {addr}:{port};'}
    loader = FileSystemLoader('.')
    env = Environment(loader=loader)
    tmpl = env.get_template('nginx.tmpl')
    buff = tmpl.render(content=cont)
    print(f'{Colors.warn}{buff}{Colors.end}')  # debug

    conf = await read_nginx_conf(name)
    if not conf or not conf == buff:
        await write_nginx_conf(name, buff)
        await reload_nginx_confs()


async def reload_nginx_confs() -> None:
    """ reload nginx configuration """
    print(f'> nginx reload')  # debug
    system('nginx -s reload')


async def check_container(container) -> bool:
    """ check the container for a valid label, ip, port """
    name = container.name
    labels = container.labels
    label = False  # skip unnecessary labels
    addr = await get_ip_addr(container)  # without an address, the container provides nothing
    port = await get_port(container)  # without a port, the container provides nothing
    for key, val in labels.items():
        if val == container_filter['label']:
            label = True
    if addr and port and label:
        print(f'{Colors.cyan}> check {name} ({addr}:{port}{Colors.end})')  # debug
        return True
    return False


async def update_nginx_conf(container, action='start') -> None:
    """ creates or deletes a config file for the container then restarts nginx """
    print(f"{Colors.cyan}> update {container.name} (action: {action}, status: {container.status}){Colors.end}")  # debug
    if await check_container(container) and container.status == 'running' or 'Up' in container.status:
        await create_nginx_conf(container)
    if container.status == 'exited' or container.status == 'removing' or 'Exited' in container.status:
        await remove_nginx_conf(container)
        await reload_nginx_confs()


async def listen_docker_events() -> None:
    """ listen to docker events """
    event_actions = ['stop', 'start']  # 'restart', 'create', 'destroy'
    events = client.events(decode=True)
    for event in events:
        if event['Type'] == 'container' and event['Action'] in event_actions:
            name = event['Actor']['Attributes']['name']
            container = client.containers.get(name)
            if container.status in container_statuses:
                print(f'{Colors.green}> get event{Colors.end}')  # debug
                await update_nginx_conf(container)
        # await sleep(0.1)  # loop
    events.close()


async def check_docker_containers() -> None:
    """ check existing containers """
    # while True:  # loop
    print(f'{Colors.green}> check containers{Colors.end}')  # debug
    containers = client.containers.list(all=True, filters=container_filter)
    for container in containers:
        if await check_container(container) and container.status in container_statuses:
            await update_nginx_conf(container)
    # await sleep(container_find_time)  # loop


async def main():
    check = create_task(check_docker_containers())
    listen = create_task(listen_docker_events())
    await check
    await listen


if __name__ == '__main__':
    try:
        run(main())
    except KeyboardInterrupt:
        exit()
