#!/usr/bin/env python
# Original By: John Baab
# Email: rhpot1991@ubuntu.com
# Updated By: Jay Schulman
# Email: info@jayschulman.com
# Updated Again By: Philip Rosenberg-Watt
# And a little again by: Vicente Monroig (vmonroig@digitaldisseny.com)
# Purpose: syncs contacts from google to asterisk server
# Updates: Updating for Google API v3 with support for Google Apps
#          OAuth2 auth flow and tokens
# Requirements: python, gdata python client, asterisk
#
# License:
#
# This Package is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 3 of the License, or (at your option) any later version.
#
# This package is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public
# License along with this package; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
# On Debian & Ubuntu systems, a complete copy of the GPL can be found under
# /usr/share/common-licenses/GPL-3, or (at your option) any later version
 
import atom,re,sys,os
import json
import gdata.data
import gdata.auth
import gdata.contacts
import gdata.contacts.client
import gdata.contacts.data
import argparse
import unicodedata
from oauth2client import client
from oauth2client import file
from oauth2client import tools

# Native application Client ID JSON from the Google Developers Console,
# store in the same directory as this script:
CLIENT_SECRETS_JSON = 'client_secret_XXXXXXXXXXX-yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy.apps.googleusercontent.com.json'


parent_parsers = [tools.argparser]
parser = argparse.ArgumentParser(parents=parent_parsers)
parser.add_argument("--allgroups", help="only works in combination with --group to show members with multiple groups", action="store_true", default=False)
parser.add_argument("--anygroup", help="show members of any user-created group (not My Contacts), OVERRIDES other options", action="store_true", default=False)
parser.add_argument("--asterisk", help="send commands to Asterisk instead of printing to console", action="store_true", default=False)
parser.add_argument("--dbname", help="database tree to use")
parser.add_argument("--delete", help="delete the existing database first", action="store_true", default=False)
parser.add_argument("--group", action="append", help="group name, can use multiple times")
parser.add_argument("--non_interactive", help="abort script if credentials are missing or invalid", action="store_true", default=False)
parser.add_argument("--ascii", help="remove all non-ascii characters from names", action="store_true", default=False)
parser.add_argument("--add_type", help="append ' - type' to name entry", action="store_true", default=False)
args = parser.parse_args()


if args.dbname is None:
    args.dbname = "cidname"

phone_map = {2: ["A", "B", "C"],
             3: ["D", "E", "F"],
             4: ["G", "H", "I"],
             5: ["J", "K", "L"],
             6: ["M", "N", "O"],
             7: ["P", "Q", "R", "S"],
             8: ["T", "U", "V"],
             9: ["W", "X", "Y", "Z"]}

phone_map_one2one = {}
for k, v in phone_map.items():
    for l in v:
        phone_map_one2one[l] = str(k)

 
def phone_translate(phone_number):
    new_number = ""
    for l in phone_number:    
        if l.upper() in phone_map_one2one.keys():
            new_number += phone_map_one2one[l.upper()]
        else:
            l = re.sub('[^0-9]', '', l)
            new_number += l
    if len(new_number) == 11 and new_number[0] == "1":
        new_number = new_number[1:]
    return new_number


def get_auth_token():
    scope = 'https://www.googleapis.com/auth/contacts.readonly'
    user_agent = __name__
    client_secrets = os.path.join(os.path.dirname(__file__), CLIENT_SECRETS_JSON)
    filename = os.path.splitext(__file__)[0] + '.dat'

    flow = client.flow_from_clientsecrets(client_secrets, scope=scope, message=tools.message_if_missing(client_secrets))
    
    storage = file.Storage(filename)
    credentials = storage.get()
    if credentials is None or credentials.invalid:
        if args.non_interactive:
            sys.stderr.write('ERROR: Invalid or missing Oauth2 credentials. To reset auth flow manually, run without --non_interactive\n')
            sys.exit(1)
        else:
            credentials = tools.run_flow(flow, storage, args)

    j = json.loads(open(filename).read())

    return gdata.gauth.OAuth2Token(j['client_id'], j['client_secret'], scope, user_agent, access_token = j['access_token'], refresh_token = j['refresh_token'])


def add_to_asterisk(dbname, cid, name):
    command = "asterisk -rx \'database put " + dbname + " " + cid + " \"" + name + "\"\'"
    if args.asterisk:
        os.system(command.encode('utf8'))
    else:
        print command.encode('utf8')

def main():
    # Change this if you aren't in the US.  If you have more than one country code in your contacts,
    # then use an empty string and make sure that each number has a country code.
    country_code = ""
    
    token = get_auth_token()
    gd_client = gdata.contacts.client.ContactsClient()
    gd_client = token.authorize(gd_client)
    qry = gdata.contacts.client.ContactsQuery(max_results=2000)
    feed = gd_client.GetContacts(query=qry)
    
    groups = {}
    gq = gd_client.GetGroups()
    for e in gq.entry:
        striptext = "System Group: "
        groupname = e.title.text
        if groupname.startswith(striptext):
            groupname = groupname[len(striptext):]
        groups[e.id.text] = groupname
 
    # delete all of our contacts before we refetch them, this will allow deletions
    if args.delete:
        command = "asterisk -rx \'database deltree %s\'" % args.dbname
        if args.asterisk:
            os.system(command)
        else:
            print command

    # for each phone number in the contacts
    for i, entry in enumerate(feed.entry):
                
        glist = []
        for grp in entry.group_membership_info:
            glist.append(groups[grp.href])

        name = None
        
        if entry.organization is not None and entry.organization.name is not None:
            name = entry.organization.name.text
        
        if entry.title.text is not None:
            name = entry.title.text
            
        if entry.nickname is not None:
            name = entry.nickname.text
            
        for r in entry.relation:
            if r.label == "CID":
                name = r.text
                break

        for phone in entry.phone_number:

            if phone.text is None:
                sys.stderr.write("ERROR: The following entry has no phone.text value:\n")
                sys.stderr.write(str(entry) + "\n")
                sys.stderr.write("The script is unable to proceed without a phone number.")
                exit(1)

            # Strip out any non numeric characters and convert to UTF-8
#             phone.text = re.sub('[^0-9]', '', phone.text)
            phone.text = phone.text.encode('utf-8')
            phone.text = phone_translate(phone.text)

            # Remove leading digit if it exists, we will add this again later for all numbers
            # Only if a country code is defined.
            if country_code != "":
                phone.text = re.compile('^\+?%s' % country_code, '', phone.text)
            
            phone.text = country_code + phone.text

            if name is None:
                sys.stderr.write("ERROR: The following entry has no way to determine a name:\n")
                sys.stderr.write(str(entry) + "\n")
                sys.stderr.write("Please fix this entry and re-run the script.\n")
                break

            name = name.replace('\'','')
            name = name.replace('"','')

            suffix = ""

            if phone.rel is not None:
                rel = phone.rel.split("#")

                if args.add_type:
                    suffix = " - " + rel[-1]

            if args.ascii:
                if not isinstance(name, bytes):
                    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore')
                if not isinstance(suffix, bytes):
                    suffix = unicodedata.normalize('NFKD', suffix).encode('ascii', 'ignore')


            if args.anygroup:
                if (("My Contacts" in glist and len(glist) > 1) or
                    ("My Contacts" not in glist and len(glist) > 0)):
                    add_to_asterisk(args.dbname, phone.text, name + suffix)
            else:
                if args.group:
                    if args.allgroups:
                        if set(args.group).issubset(glist):
                            add_to_asterisk(args.dbname, phone.text, name + suffix)
                    else:
                        for g in args.group:
                            if g in glist:
                                add_to_asterisk(args.dbname, phone.text, name + suffix)
                else:
                    add_to_asterisk(args.dbname, phone.text, name + suffix)

 
if __name__ == '__main__':
    main()
