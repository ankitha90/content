import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *
''' IMPORTS '''

import json
import requests
from distutils.util import strtobool
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as parsedate

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' GLOBALS/PARAMS '''

PARAMS = demisto.params()
USERNAME = PARAMS.get('credentials').get('identifier')
PASSWORD = PARAMS.get('credentials').get('password')
# Remove trailing slash to prevent wrong URL path to service
BASE_URL = PARAMS.get('url', '').strip().rstrip('/')
# Should we use SSL
USE_SSL = not PARAMS.get('insecure', False)
AUTH = ''
LAST_JWT_FETCH = None
# Default JWT validity time set in Forescout Web API
JWT_VALIDITY_TIME = timedelta(minutes=5)
# For use of Entity Tags (ETags) to reduce bandwidth by eliminating transactions
# when previously reported data hasn't changed.
ETAGS = {}


''' HELPER FUNCTIONS '''


def format_policies_data(data):
    """
    Return policies formatted to Demisto standards

    Parameters
    ----------
    data : dict
        The data returned from making API call to Forescout Web API policies endpoint

    Returns
    -------
    list
        Formatted Policies
    """
    formatted_policies = []
    policies = data.get('policies', [])
    for policy in policies:
        formatted_policy = {
            'ID': policy.get('policyId'),
            'Name': policy.get('name'),
            'Description': policy.get('description')
        }
        formatted_rules = []
        rules = policy.get('rules', [])
        for rule in rules:
            formatted_rule = {
                'ID': rule.get('ruleId'),
                'Name': rule.get('name'),
                'Description': rule.get('description')
            }
            formatted_rules.append(formatted_rule)
        formatted_policy['Rule'] = formatted_rules
        formatted_policies.append(formatted_policy)
    return formatted_policies


def create_web_api_headers(entity_tag=''):
    """
    Return headers object that formats to Forescout Web API expectations and takes
    into account if an entity tag exists for a request to an endpoint.

    Parameters
    ----------
    entity_tag : str
        Entity tag to include in the headers if not None.

    Returns
    -------
    dict
        Headers object for the Forescout Web API calls
    """
    headers = {
        'Authorization': AUTH,
        'Accept': 'application/hal+json'
    }
    if entity_tag:
        headers['If-None-Match'] = entity_tag
    return headers


def log_entity_tag(api_calling_func):
    def api_calling_func_wrapper(*args, **kwargs):
        response = api_calling_func(*args, **kwargs)
        etag_hash = response.headers.get('ETag')
        cur_etag = ETAGS.setdefault(api_calling_func.__qualname__, etag_hash)
        if cur_etag != etag_hash:
            ETAGS[api_calling_func.__qualname__] = etag_hash
        return response
    return api_calling_func_wrapper


def login():
    global LAST_JWT_FETCH
    global AUTH
    if not LAST_JWT_FETCH or datetime.now(timezone.utc) >= LAST_JWT_FETCH + JWT_VALIDITY_TIME:
        url_suffix = '/api/login'
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        params = {'username': USERNAME, 'password': PASSWORD}
        response = http_request('POST', url_suffix, headers=headers, params=params, resp_type='response')
        fetch_time = parsedate(response.headers.get('Date', ''))
        AUTH = response.text
        LAST_JWT_FETCH = fetch_time


def http_request(method, url_suffix, full_url=None, headers=None,
                 auth=None, params=None, data=None, files=None, resp_type='json'):
    """
    A wrapper for requests lib to send our requests and handle requests
    and responses better

    Parameters
    ----------
    method : str
        HTTP method, e.g. 'GET', 'POST' ... etc.
    url_suffix : str
        API endpoint.
    full_url : str
        Bypasses the use of BASE_URL + url_suffix. Useful if there is a need to
        make a request to an address outside of the scope of the integration
        API.
    headers : dict
        Headers to send in the request.
    auth : tuple
        Auth tuple to enable Basic/Digest/Custom HTTP Auth.
    params : dict
        URL parameters.
    data : dict
        Data to be sent in a 'POST' request.
    files : dict
        File data to be sent in a 'POST' request.
    resp_type : str
        Determines what to return from having made the HTTP request. The default
        is 'json'. Other options are 'text', 'content' or 'response' if the user
        would like the full response object returned.

    Returns
    -------
    dict
        Response JSON from having made the request.
    """
    try:
        address = full_url if full_url else BASE_URL + url_suffix
        res = requests.request(
            method,
            address,
            verify=USE_SSL,
            params=params,
            data=data,
            files=files,
            headers=headers,
            auth=auth
        )

        # Handle error responses gracefully
        if res.status_code not in {200, 201, 304}:
            err_msg = 'Error in Forescout Integration API call [{}] - {}'.format(res.status_code, res.reason)
            try:
                res_json = res.json()
                if res_json.get('error'):
                    err_msg += '\n{}'.format(res_json.get('message'))
                return_error(err_msg)
            except json.decoder.JSONDecodeError:
                return_error(err_msg)

        resp_type = resp_type.casefold()
        if resp_type == 'json':
            return res.json()
        elif resp_type == 'text':
            return res.text
        elif resp_type == 'content':
            return res.content
        else:
            return res

    # except json.decoder.JSONDecodeError:
    #     if res.text != '':
    #         return res
    #     else:
    #         return return_error('No contents in the response.')
    except requests.exceptions.ConnectionError:
        err_msg = 'Connection Error - Check that the Server URL parameter is correct.'
        return_error(err_msg)


''' COMMANDS + REQUESTS FUNCTIONS '''


def test_module():
    """
    Performs basic get request that requires proper authentication
    """
    login()
    demisto.results('ok')


def get_items_command():
    """
    Gets details about a items using IDs or some other filters
    """
    # Init main vars
    headers = []
    contents = []
    context = {}
    context_entries = []
    title = ''
    # Get arguments from user
    item_ids = argToList(demisto.args().get('item_ids', []))
    is_active = bool(strtobool(demisto.args().get('is_active', 'false')))
    limit = int(demisto.args().get('limit', 10))
    # Make request and get raw response
    items = get_items_request(item_ids, is_active)
    # Parse response into context & content entries
    if items:
        if limit:
            items = items[:limit]
        title = 'Example - Getting Items Details'

        for item in items:
            contents.append({
                'ID': item.get('id'),
                'Description': item.get('description'),
                'Name': item.get('name'),
                'Created Date': item.get('createdDate')
            })
            context_entries.append({
                'ID': item.get('id'),
                'Description': item.get('description'),
                'Name': item.get('name'),
                'CreatedDate': item.get('createdDate')
            })

        context['Example.Item(val.ID && val.ID === obj.ID)'] = context_entries

    demisto.results({
        'Type': entryTypes['note'],
        'ContentsFormat': formats['json'],
        'Contents': contents,
        'ReadableContentsFormat': formats['markdown'],
        'HumanReadable': tableToMarkdown(title, contents, removeNull=True),
        'EntryContext': context
    })


def get_items_request(item_ids, is_active):
    # The service endpoint to request from
    endpoint_url = 'items'
    # Dictionary of params for the request
    params = {
        'ids': item_ids,
        'isActive': is_active
    }
    # Send a request using our http_request wrapper
    response = http_request('GET', endpoint_url, params)
    # Check if response contains errors
    if response.get('errors'):
        return_error(response.get('errors'))
    # Check if response contains any data to parse
    if 'data' in response:
        return response.get('data')
    # If neither was found, return back empty results
    return {}


@log_entity_tag
def get_host(args):
    identifier = args.get('identifier', '')
    fields = args.get('fields', '')
    login()
    url_suffix = '/api/hosts/'
    id_type, *ident = identifier.split('=')
    id_type = id_type.casefold()
    if len(ident) != 1 or id_type not in {'id', 'ip', 'mac'}:
        err_msg = 'The entered endpoint identifier should be prefaced by the identifier type,' \
                ' (\'ip\', \'mac\', or \'id\') followed by \'=\' and the actual ' \
                'identifier, e.g. \'ip=123.123.123.123\'.' #disable-secrets-detection
        raise ValueError(err_msg)

    if id_type == 'ip':
        # API endpoint format - https://{EM.IP}/api/hosts/ip/{ipv4}?fields={prop},..,{prop_n}
        url_suffix += 'ip/'
    elif id_type == 'mac':
        # API endpoint format - https://{EM.IP}/api/hosts/mac/{mac}?fields={prop},..,{prop_n}
        url_suffix += 'mac/'
    # if id_type == 'id' don't change url_suffix -it's already in desired format as shown below
    # API endpoint format - https://{EM.IP}/api/hosts/{obj_ID}?fields={prop},..,{prop_n}

    url_suffix += ident[0]
    params = {'fields': fields} if fields != '' else None
    headers = {
        'Authorization': AUTH,
        'Accept': 'application/hal+json'
    }
    entity_tag = ETAGS.get('get_host')
    if entity_tag:
        headers['If-None-Match'] = entity_tag
    response = http_request('GET', url_suffix, headers=headers, params=params, resp_type='response')
    return response


def get_host_command():
    args = demisto.args()
    identifier = args.get('identifier', '')
    response = get_host(args)
    host = response.get('host', {})
    fields = host.get('fields', {})
    content = {
        'ID': host.get('id'),
        'IP': host.get('ip'),
        'MAC': host.get('mac'),
        'EndpointURL': response.get('_links', {}).get('self', {}).get('href'),
        'Field': fields
    }
    context = {'Forescout.Host(val.ID && val.ID === obj.ID)': content}
    title = 'Endpoint Details for {}'.format(identifier) if identifier else 'Endpoint Details'
    human_readable = tableToMarkdown(title, content, removeNull=True)
    return_outputs(readable_output=human_readable, outputs=context, raw_response=response)

@log_entity_tag
def get_hosts():
    login()
    url_suffix = '/api/hosts'
    headers = {
        'Authorization': AUTH,
        'Accept': 'application/hal+json'
    }
    entity_tag = ETAGS.get('get_hosts')
    if entity_tag:
        headers['If-None-Match'] = entity_tag
    params = {}
    response = http_request('GET', url_suffix, headers=headers, params=params, resp_type='response')
    return response


def get_hosts_command():
    response = get_hosts().json()
    content = [
        {
            'ID': x.get('hostId'),
            'IP': x.get('ip'),
            'MAC': x.get('mac'),
            'EndpointURL': x.get('_links', {}).get('self', {}).get('href')
        } for x in response.get('hosts', [])
    ]
    context = {'Forescout.Host(val.ID && val.ID === obj.ID)': content}
    title = 'Active Endpoints'
    human_readable = tableToMarkdown(title, content, removeNull=True)
    return_outputs(readable_output=human_readable, outputs=context, raw_response=response)


@log_entity_tag
def get_hostfields():
    login()
    url_suffix = '/api/hostfields'
    headers = {
        'Authorization': AUTH,
        'Accept': 'application/hal+json'
    }
    entity_tag = ETAGS.get('get_hosts')
    if entity_tag:
        headers['If-None-Match'] = entity_tag
    params = {}
    response = http_request('GET', url_suffix, headers=headers, params=params, resp_type='response')
    return response


def get_hostfields_command():
    response = get_hostfields()
    data = response.json()
    content = [{key.title(): val for key, val in x.items()} for x in data.get('hostFields', [])]
    context = {'Forescout.HostField': content}
    title = 'Index of Host Properties'
    human_readable = tableToMarkdown(title, content, removeNull=True)
    return_outputs(readable_output=human_readable, outputs=context, raw_response=data)


@log_entity_tag
def get_policies():
    url_suffix = '/api/policies'
    entity_tag = ETAGS.get('get_policies')
    headers = create_web_api_headers(entity_tag)
    response = http_request('GET', url_suffix, headers=headers, resp_type='response')
    return response


def get_policies_command():
    response = get_policies()
    data = response.json()
    content = format_policies_data(data)
    context = {'Forescout.Policy(val.ID && val.ID === obj.ID)': content}
    title = 'Forescout Policies'
    human_readable = tableToMarkdown(title, content, removeNull=True)
    return_outputs(readable_output=human_readable, outputs=context, raw_response=data)



def update_host_properties()
    pass


def update_host_properties_command()
    pass


''' COMMANDS MANAGER / SWITCH PANEL '''

COMMANDS = {
    'test-module': test_module,
    'forescout-get-host': get_host_command,
    'forescout-get-hosts': get_hosts_command,
    'forescout-get-hostfields': get_hostfields_command,
    'forescout-get-policies': get_policies_command,
    'forescout-update-host-properties': update_host_properties_command
}

''' EXECUTION '''


def main():
    """Main execution block"""

    try:
        # Remove proxy if not set to true in params
        handle_proxy()

        cmd_name = demisto.command()
        LOG('Command being called is {}'.format((cmd_name)))

        if cmd_name in COMMANDS.keys():
            COMMANDS[cmd_name]()

    # Log exceptions
    except Exception as e:
        LOG(str(e))
        LOG.print_log()
        raise


# python2 uses __builtin__ python3 uses builtins
if __name__ == '__builtin__' or __name__ == 'builtins':
    main()
