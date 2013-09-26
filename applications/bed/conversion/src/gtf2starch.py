#!/usr/bin/env python

#
#    BEDOPS
#    Copyright (C) 2011, 2012, 2013 Shane Neph, Scott Kuehn and Alex Reynolds
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

#
# Author:       Alex Reynolds
#
# Project:      Converts 1-based, closed [a,b] GTF2.2 input
#               into 0-based, half-open [a-1,b) six-column extended BED
#               and thence compressed into a BEDOPS Starch archive sent
#               to standard output.
#
# Version:      2.3
#
# Notes:        The GTF2.2 specification (http://mblab.wustl.edu/GTF22.html)
#               contains columns that do not map directly to common or UCSC BED columns.
#               Therefore, we add the following columns to preserve the ability to 
#               seamlessly convert back to GTF after performing operations with 
#               BEDOPS or other tools.
#
#               - The 'source' GTF column data maps to the 7th BED column
#               - The 'feature' data maps to the 8th BED column
#               - The 'frame' data maps to the 9th BED column
#               - The 'attributes' data maps to the 10th BED column
#               - The 'comments' data (if present) maps to the 11th BED column
#
#               We make the following assumptions about the GTF input data:
#
#               - The 'seqname' GTF column data maps to the chromosome label (1st BED column)
#               - The 'gene_id' attribute in the 'attributes' GTF column (if present) maps to 
#                 the element ID (4th BED column)
#               - The 'score' and 'strand' GFF columns (if present) are mapped to the
#                 5th and 6th BED columns, respectively
#
#               If we encounter zero-length insertion elements (which are defined
#               where the start and stop GTF column data values are equivalent), the 
#               start coordinate is decremented to convert to 0-based, half-open indexing, 
#               and a 'zero_length_insertion' attribute is added to the 'attributes' GTF 
#               column data.
#
#               Example usage:
#
#               $ gtf2starch < foo.gtf > sorted-foo.gtf.bed.starch
#
#               We make no assumptions about sort order from converted output. Apply
#               the usage case displayed to pass data to the BEDOPS sort-bed application, 
#               which generates lexicographically-sorted BED data as output.
#
#               If you want to skip sorting, use the --do-not-sort option:
#
#               $ gtf2starch --do-not-sort < foo.gtf > unsorted-foo.gtf.bed.starch
#

import getopt, sys, os, stat, subprocess, tempfile

def printUsage(stream):
    usage = ("Usage:\n"
             "  %s [ --help ] [ --do-not-sort | --max-mem <value> ] [ --starch-format <bzip2|gzip> ] < foo.gtf > sorted-foo.gtf.bed.starch\n\n"
             "Options:\n"
             "  --help                        Print this help message and exit\n"
             "  --do-not-sort                 Do not sort converted data with BEDOPS sort-bed\n"
             "  --max-mem <value>             Sets aside <value> memory for sorting BED output.\n"
             "                                For example, <value> can be 8G, 8000M or 8000000000\n"
             "                                to specify 8 GB of memory (default: 2G).\n"
             "  --starch-format <bzip2|gzip>  Specify backend compression format of starch\n"
             "                                archive (default: bzip2).\n\n"
             "About:\n"
             "  This script converts 1-based, closed [a,b] GTF2.2 data from standard\n"
             "  input into 0-based, half-open [a-1,b) six-column extended BED, sorted and\n"
             "  thence made into a BEDOPS Starch archive sent to standard output.\n\n"
             "  The GTF2.2 specification (http://mblab.wustl.edu/GTF22.html)\n"
             "  contains columns that do not map directly to common or UCSC BED columns.\n"
             "  Therefore, we add the following columns to preserve the ability to\n"
             "  seamlessly convert back to GTF after performing operations with\n"
             "  BEDOPS or other tools.\n\n"
             "  - The 'source' GTF column data maps to the 7th BED column\n"
             "  - The 'feature' data maps to the 8th BED column\n"
             "  - The 'frame' data maps to the 9th BED column\n"
             "  - The 'attributes' data maps to the 10th BED column\n"
             "  - The 'comments' data (if present) maps to the 11th BED column\n\n"
             "  We make the following assumptions about the GTF input data:\n\n"
             "  - The 'seqname' GTF column data maps to the chromosome label (1st BED column)\n"
             "  - The 'gene_id' attribute in the 'attributes' GTF column (if present) maps to\n"
             "    the element ID (4th BED column)\n"
             "  - The 'score' and 'strand' GFF columns (if present) are mapped to the\n"
             "    5th and 6th BED columns, respectively\n\n"
             "  If we encounter zero-length insertion elements (which are defined\n"
             "  where the start and stop GTF column data values are equivalent), the\n"
             "  start coordinate is decremented to convert to 0-based, half-open indexing,\n"
             "  and a 'zero_length_insertion' attribute is added to the 'attributes' GTF\n"
             "  column data.\n\n"
             "Example:\n"
             "  $ %s < foo.gtf > sorted-foo.gtf.bed.starch\n\n"
             "  We make no assumptions about sort order from converted output. Apply\n"
             "  the usage case displayed to pass data to the BEDOPS sort-bed application,\n"
             "  which generates lexicographically-sorted BED data as output.\n\n"
             "  If you want to skip sorting, use the --do-not-sort option:\n\n"
             "  $ gtf2bed --do-not-sort < foo.gtf > unsorted-foo.gtf.bed.starch\n\n"
             % (sys.argv[0], sys.argv[0]))
    if stream is "stdout":
        sys.stdout.write(usage)
    elif stream is "stderr":
        sys.stderr.write(usage)
    return os.EX_OK

def checkInstallation(rv):
    currentVersion = sys.version_info
    if currentVersion[0] == rv[0] and currentVersion[1] >= rv[1]:
        pass
    else:
        sys.stderr.write( "[%s] - Error: Your Python interpreter must be %d.%d or greater (within major version %d)\n" % (sys.argv[0], rv[0], rv[1], rv[0]) )
        sys.exit(os.EX_CONFIG)
    return os.EX_OK

def main(*args):
    requiredVersion = (2,5)
    checkInstallation(requiredVersion)

    sortOutput = True
    maxMem = "2G"
    maxMemChanged = False
    starchFormat = "bzip2"
    
    optstr = ""
    longopts = ["help", "do-not-sort", "max-mem=", "starch-format="]
    try:
        (options, args) = getopt.getopt(sys.argv[1:], optstr, longopts)
    except getopt.GetoptError as error:
        sys.stderr.write( "[%s] - Error: %s\n" % (sys.argv[0], str(error)) )
        printUsage("stderr")
        return os.EX_USAGE
    for key, value in options:
        if key in ("--help"):
            printUsage("stdout")
            return os.EX_OK
        elif key in ("--do-not-sort"):
            sortOutput = False
        elif key in ("--max-mem"):
            maxMem = str(value)
            maxMemChanged = True
        elif key in ("--starch-format"):
            starchFormat = str(value)

    starchFormat = "--" + starchFormat            

    if maxMemChanged:
        sys.stderr.write( "[%s] - Warning: The --max-mem parameter is currently ignored (cf. https://github.com/bedops/bedops/issues/1 )\n" % sys.argv[0] )

    if maxMemChanged and not sortOutput:
        sys.stderr.write( "[%s] - Error: Cannot specify both --do-not-sort and --max-mem parameters\n" % sys.argv[0] )
        printUsage("stderr")
        return os.EX_USAGE
    
    mode = os.fstat(0).st_mode
    inputIsNotAvailable = True
    if stat.S_ISFIFO(mode) or stat.S_ISREG(mode):
        inputIsNotAvailable = False
    if inputIsNotAvailable:
        sys.stderr.write( "[%s] - Error: Please redirect or pipe in GTF-formatted data\n" % sys.argv[0] )
        printUsage("stderr")
        return os.EX_NOINPUT

    starchTF = tempfile.NamedTemporaryFile(mode='wb')
    if sortOutput:
        sortTF = tempfile.NamedTemporaryFile(mode='wb', delete=False)

    for line in sys.stdin:
        chomped_line = line.rstrip(os.linesep)
        if chomped_line.startswith('##'):
            pass
        elif chomped_line.startswith('track'):
            # we do not support non-standard use of track keyword by Ensembl 
            pass
        else:
            elems = chomped_line.split('\t')
            cols = dict()
            cols['seqname'] = elems[0].lstrip(' ') # strip leading whitespace
            cols['source'] = elems[1]
            cols['feature'] = elems[2]
            cols['start'] = int(elems[3])
            cols['end'] = int(elems[4])
            cols['score'] = elems[5]
            cols['strand'] = elems[6]
            cols['frame'] = elems[7]
            cols['attributes'] = elems[8].rstrip(' ') # strip trailing whitespace
            try:
                cols['comments'] = elems[9]
            except IndexError:
                cols['comments'] = None

            attrd = dict()
            attrs = map(lambda s: s.split(' '), cols['attributes'].split('; '))
            for attr in attrs:
                attrd[attr[0]] = attr[1]

            cols['chr'] = cols['seqname']
            try:
                cols['id'] = attrd['gene_name'].replace('"', '').strip().rstrip(';')
            except KeyError:
                try:
                    cols['id'] = attrd['gene_id'].replace('"', '').strip().rstrip(';')
                except KeyError:
                    cols['id'] = '.'

            if cols['start'] == cols['end']:
                cols['start'] -= 1
                cols['attributes'] = ' '.join([cols['attributes'], "zero_length_insertion \"True\";"])
            else:
                cols['start'] -= 1

            if not cols['comments']:
                convertedLine = '\t'.join([cols['chr'], 
                                           str(cols['start']),
                                           str(cols['end']),
                                           cols['id'],
                                           cols['score'],
                                           cols['strand'],
                                           cols['source'],
                                           cols['feature'],
                                           cols['frame'],
                                           cols['attributes']]) + '\n'
            else:
                convertedLine = '\t'.join([cols['chr'], 
                                           str(cols['start']),
                                           str(cols['end']),
                                           cols['id'],
                                           cols['score'],
                                           cols['strand'],
                                           cols['source'],
                                           cols['feature'],
                                           cols['frame'],
                                           cols['attributes'],
                                           cols['comments']]) + '\n'
                
            if sortOutput:
                sortTF.write(convertedLine)
            else:
                starchTF.write(convertedLine)

    if sortOutput:
        sortTF.close()
        # --max-mem disabled until sort-bed issue is fixed (cf. https://github.com/bedops/bedops/issues/1 )
        # sortProcess = subprocess.Popen(["sort-bed", "--max-mem", maxMem, sortTF.name], stdout=starchTF)
        sortProcess = subprocess.Popen(["sort-bed", sortTF.name], stdout=starchTF)
        sortProcess.wait()
        try:
            os.remove(sortTF.name)
        except OSError:
            sys.stderr.write( "[%s] - Warning: Could not delete intermediate sorted file [%s]\n" % (sys.argv[0], sortTF.name) )

    starchProcess = subprocess.Popen(["starch", starchFormat, starchTF.name])
    starchProcess.wait()
        
    return os.EX_OK

if __name__ == '__main__':
    sys.exit(main(*sys.argv))
