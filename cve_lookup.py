import sys
import re
from collections import defaultdict

# preload XML
import xml.etree.cElementTree as ET
import defusedxml.cElementTree as DET
import re
import glob
import os

from Cython.Shadow import other_types

xmlstring = []



def parse_dbs(folder):
    """
    parse the XML dbs and build an in-memory lookup
    :param folder: the folder full of *.xml files
    :return:
    """
    root = None
    for filename in glob.glob(folder+'/*.xml'):
        with open(filename) as f:
            db_string = f.read() # remove the annoying namespace
            db_string = re.sub(' xmlns="[^"]+"', '', db_string, count=1)
            # xmlstring.append(db_string)
            data = ET.fromstring(db_string)
            if root is None:
                root = data
            else:
                root.extend(data)

    return root


#root = ET.fromstring("\n".join(xmlstring))
# namespace ="http://nvd.nist.gov/feeds/cve/1.2"

def etree_to_dict(t):
    """
    Change the xml tree to an easy to use python dict
    :param t: the xml tree
    :return: a dict representation
    """
    d = {t.tag: {} if t.attrib else None}
    children = list(t)
    if children:
        dd = defaultdict(list)
        for dc in map(etree_to_dict, children):
            for k, v in dc.iteritems():
                dd[k].append(v)
        d = {t.tag: {k:v[0] if len(v) == 1 else v for k, v in dd.iteritems()}}
    if t.attrib:
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.iteritems())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
              d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d


def get_packages_swid(package_list):
    """
    Get the packages from a swid string
    :param package_strs:
    :return:
    """
    package_xml = None
    packages = defaultdict(set)
    errors = []
    for xml_doc in package_list.split("\n"):
        try:
            # remove the <? ?> if any
            xml_doc = re.sub('<\?[^>]+\?>', '', xml_doc)
            # use DET since this is untrusted data
            data = DET.fromstring(xml_doc)
            name, version = data.attrib['name'], data.attrib['version']
            version = version.split("-")[0]
            packages[name].add(version)

        except Exception as e:
            errors.append(str(e))

    return errors, packages

def get_packages_rpm(package_list):
    """
    Get the packages from an rpm string
    :param package_strs:
    :return:
    """
    package_strs = package_list.split("\n")
    packages = defaultdict(set)
    errors = []
    for x in package_strs:
        m = re.search(r'(.*/)*(.*)-(.*)-(.*?)\.(.*)', x)
        if m:
            (path, name, version, release, platform) = m.groups()
            packages[name].add(version)
            # print "\t".join([path, name, verrel, version, release, platform])
        else:
            errors.append('ERROR: Invalid name: %s\n' % x)

    return errors, packages


def get_packages_ls(package_list):
    """
    Get the packages from a string generated by ls in /lib or /usr/lib
    :param package_list:
    :return:
    """
    package_strs = re.split(r"[\t\n ]+", package_list)
    packages = defaultdict(set)
    errors = []
    for x in package_strs:
        m = re.search(r'(.+)\.so\.([\d\.]+).*', os.path.basename(x))
        if m:
            (name, version) = m.groups()
            # remove 'lib' prefix
            if name.startswith("lib"):
                name = name[3:]
            packages[name].add(version)

            print name, version
            # print "\t".join([path, name, verrel, version, release, platform])
        else:
            errors.append('ERROR: Invalid name: %s\n' % x)

    return errors, packages

def get_packages_wmic(package_list):
    """
    Get packages from a windows system using wmic
    :param package_lis:
    :return:
    """
    package_strs = re.split(r"\r?\n+", package_list)
    packages = defaultdict(set)
    errors = []

    def add_package(name, version):
        """
        Some packages are labeled in the NVD by package name WITHOUT the vendor name prepended
        but wmic, gives us the full package name with the Vendor name (e.g. we're given 'Adobe Flash Player' and the
        NVD wants 'flash_player'.

        TODO: Maybe also look at CPE? That could solve a lot of these issues with naming

        :param packages:
        :param name:
        :param version:
        :return:
        """
        # add the name itself
        packages[name].add(version)
        # now try and trip out vendor name
        try:
            # vendors always put their name first because they're egotistical like that
            vendor, stripped_name = name.split(" ", 1)
            # replace space with _, everything to lowercase and trim it
            stripped_name = stripped_name.strip().lower().replace(" ", "_")
            packages[stripped_name].add(version)
        except ValueError:  # thrown if there was <2 words in the string
            pass


    for line in package_strs:
        try:
            columns = line.split(",")

            name, version = columns[1].strip(), columns[5]
            # remove any version numbers from name
            # TODO: Sometimes the version number pulled from here is different from the one reported
            # TODO: Let's include both right now, jsut in case
            version_re = re.search(r'([0-9.]+)\W*$', name)
            if version_re is not None:
                other_version = version_re.groups()[0]
                name = re.sub(r'[0-9.]+\W*$', '', name).rstrip()
                add_package(name, other_version)

            add_package(name, version)
        except Exception as e:
            print e
            errors.append('ERROR: Invalid line: %s\n' % line)

    print packages
    return errors, packages


formats = {"swid": get_packages_swid, "rpm": get_packages_rpm, "yocto": get_packages_rpm,
           "ls": get_packages_ls, "wmic": get_packages_wmic}


def get_package_dict(package_list, list_format=None):
    """
    Get the packages from the string
    :param package_list:
    :param list_format: The format of package_list
    :return:
    """
    #strip extraneous whitespace
    package_list =package_list.strip()
    # if format is none, try and auto-detect
    if list_format is None:
        # if we're XML, then we're probably swid
        if package_list.startswith("<?xml"):
            return get_packages_swid(package_list)
        # if the output is text, followed by comma, then more text, it's probably
        # output from wmic (see http://helpdeskgeek.com/how-to/generate-a-list-of-installed-programs-in-windows/)
        elif re.match(r'[a-zA-Z0-9_]+,+[a-zA-Z0-9_]+,', package_list):
            return get_packages_wmic(package_list)
        # if it starts with a /, then it's probably a dump from ls
        elif package_list.startswith("/"):
            return get_packages_ls(package_list)
        else:
            return get_packages_rpm(package_list)

    else:
        return formats[list_format](package_list)


def get_vulns(packages, root):
    """
    Get the vulns from a list of packages returned by get_package_dict()
    :param packages:
    :return:
    """
    result = defaultdict(list)
    for entry in root:
        for vuln_soft in entry.findall("vuln_soft"):
            for prod in vuln_soft.findall("prod"):
                if prod.attrib['name'] in packages:
                    vers = set([x.attrib['num'] for x in prod.findall("vers")])
                    intersection = set(vers).intersection(packages[prod.attrib['name']])
                    if len(intersection) > 0:
                        si = ' - ' + ','.join(intersection)
                        result[prod.attrib['name'] + si].append(etree_to_dict(entry)["entry"])
    return result
