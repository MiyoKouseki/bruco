#!/usr/bin/python

# Brute force coherence (Gabriele Vajente, 2015-06-11)
# 
# Command line arguments (with default values)
#
# --ifo                       interferometer prefix (no default, must specify)
# --channel=OAF-CAL_DARM_DQ   name of the main channel
# --gpsb=1087975458           starting time
# --length=180                amount of data to use (in seconds)
# --outfs=8192                sampling frequency of the output results (coherence will 
#                             be computed up to outfs/2 if possible)
# --minfs=512                 skip all channels with samplig frequency smaller than this
# --naver=100                 number of averages to compute the coherence
# --dir=bruco                 output directory
# --top=100                   for each frequency, save to cohtab.txt and idxtab.txt this 
#                             maximum number of coherence channels
# --webtop=20                 show this number of coherence channels per frequency, in the 
#                             web page summary
# --plot=png                  plot format (png, pdf, none)
# --nproc                     number of processes to use (if not specified, use all CPUs)
#
# Example:
# ./bruco.py --ifo=H1 --channel=CAL-DELTAL_EXTERNAL_DQ --gpsb=1111224016 --length=600 --outfs=4096 --naver=100 --dir=./bruco_1111224016 --top=100 --webtop=20
#
# To properly run the script, you need to setup a couple of more things. On line 52 you 
# must define where the lits of excluded channels is. The default is the same directory, 
# in a file called 'bruco_excluded_channels.txt'. On line 54 you must set up a scratch 
# directory where the frame library will save the temporary GWF files.
#
#
# CHANGELOG:
# 
# 2015-01-29 added linear detrending in PSD and coherence to improve low frequency bins
# 2015-02-16 - split coherence computation into PSDs and CSDs to remove redundant compuation of main channel PSD (still room to improve here)
#            - removed upsampling of channels with lower sampling rate (now coherences are always computed with the minimum possible number of samples)
# 2015-02-18 - further splitting of coherence into primitive FFTs
# 2015-02-19 - allow selection of plot output format (PDF or PNG)
# 2015-02-24 - corrected typo in options lenght -> length
#            - implemented parallel processing
# 2015-06-11 - using gw_data_find to locate the GWF files

import numpy
import os
import matplotlib
matplotlib.use("Agg", warn=False)
from optparse import OptionParser
from pylab import *
import time
from bruco_functions import *
import markup
import fnmatch
import scipy.stats
import sys
import subprocess
from glue import lal
from pylal import frutils, Fr
import multiprocessing
import itertools
import warnings
warnings.filterwarnings("ignore")

##### Options and configurations ###########################

# this file contains the list of channels to exclude
exc = 'bruco_excluded_channels.txt'
# where to save temporary gwf cache
scratchdir = '/tmp/bruco_tmp'

# do some timing
start_time = time.time()  

##### Parallelized data access and coherence computation ########
def parallelized_coherence(args):
    gpsb, gpse, ntop, outfs, npoints, s, opt, ch1_ffts, f1, psd1, channels, id, chidx = args
    print "Called parallelized_coherence(), process %d" % id

    # init tables
    cohtab = zeros((npoints/2+1, ntop))
    idxtab = zeros((npoints/2+1, ntop), dtype=int)

    # analyze every channel in the list
    for channel2,i in zip(channels,arange(len(channels))):
        print "  Process %d: channel %d of %d: %s" % (id, i+1, len(channels), channel2)
    
        # read auxiliary channel
        try:
            buffer = d.fetch(channel2, gpsb, gpse)
        except:
            print "  Process %d: some error occurred in channel %s: %s", (id, channel2, sys.exc_info())
            continue
    
        # extract the channel and the sampling frequency
        ch2 = numpy.array(buffer)
        fs2 = len(ch2) / dt
        # check if the channel is flat, and skip it if so
        if min(ch2) == max(ch2):
            print "  Process %d: %s is flat, skipping" % (id, channel2)
            continue
    
        # resample to outfs if needed
        if fs2 > outfs:
    	    # here I'm using a custom decimate function, defined in functions.py
            ch2 = decimate(ch2, int(fs2 / outfs))
    	    fs2 = outfs
    
        ###### compute coherence
        # compute all the FFTs of the aux channel (those FFTs are returned already normalized 
        # so that the MATLAB-like scaled PSD is just sum |FFT|^2
        ch2_ffts = computeFFTs(ch2, npoints*fs2/outfs, npoints*fs2/outfs/2, fs2)
        # average to get PSDs and CSDs, create frequency vector
        psd2 = mean(abs(ch2_ffts)**2,1) 
        f = linspace(0, fs2/2, npoints*fs2/outfs/2+1)
        csd12 = mean(conjugate(ch2_ffts)*ch1_ffts[0:npoints*fs2/outfs/2+1,:],1) 
        # we use the full sampling PSD of the main channel, using only the bins corresponding to channel2 sampling
        c = abs(csd12)**2/(psd2 * psd1[0:len(psd2)])
            
        # save coherence in summary table. Basically, cohtab has a row for each frequency bin and a number of
        # columns which is determined by the option --top. For each frequency bin, the new coherence value is added
        # only if it's larger than the minimum already present. Then idxtab contains again a row for each frequency 
        # bin: but in this case each entry is an unique index that determines the channel that gave that coherence.
        # So for example cohtab[100,0] gives the highest coherence for the 100th frequency bin; idxtab[100,0] contains
        # an integer id that corresponds to the channel. This id is saved in channels.txt  
        for cx,j in zip(c,arange(len(c))):
            top = cohtab[j, :]
            idx = idxtab[j, :]
            if cx > min(top):
                ttop = concatenate((top, [cx]))
                iidx = concatenate((idx, [chidx + i]))
                ii = ttop.argsort()
                ii = ii[1:]
                cohtab[j, :] = ttop[ii]
                idxtab[j, :] = iidx[ii]
                
        # create the output plot, if desired, and with the desired format
        if opt.plotformat != "none":
            figure()
            subplot(211)
            title('Coherence %s vs %s - GPS %d' % (opt.channel, channel2, gpsb), fontsize='smaller')
            loglog(f, c, f, ones(shape(f))*s, 'r--', linewidth=0.5)
            axis(xmax=outfs/2)
            axis(ymin=s/2, ymax=1)
            grid(True)
            ylabel('Coherence')
            subplot(212)
            loglog(f1, psd1[0:len(f1)])
            mask = ones(shape(f))
	    mask[c<s] = nan
            loglog(f, psd1[0:len(psd2)] * sqrt(c) * mask, 'r')
            axis(xmax=outfs/2)
            xlabel('Frequency [Hz]')
            grid(True)
            
            savefig(opt.dir + '/%s.%s' % (channel2.split(':')[1], opt.plotformat), format=opt.plotformat)
            close()
        
        del ch2, c, f
           
    print "  Process %s is done" % id
    return cohtab, idxtab, id

##### Define and get command line options ###################
parser = OptionParser()
parser.add_option("-c", "--channel", dest="channel",
                  default='OAF-CAL_DARM_DQ',
                  help="target channel", metavar="Channel")
parser.add_option("-i", "--ifo", dest="ifo",
                  default="",
                  help="interferometer", metavar="IFO")
parser.add_option("-g", "--gpsb", dest="gpsb",
                  default='1090221600',
                  help="start GPS time (-1 means now)", metavar="GpsTime")
parser.add_option("-l", "--length", dest="dt",
                  default='600',
                  help="duration in seconds", metavar="Duration")
parser.add_option("-o", "--outfs", dest="outfs",
                  default='8192',
                  help="sampling frequency", metavar="OutFs")
parser.add_option("-n", "--naver", dest="nav",
                  default='300',
                  help="number of averages", metavar="NumAver")
parser.add_option("-d", "--dir", dest="dir",
                  default='bruco_1090221600',
                  help="output directory", metavar="DestDir")
parser.add_option("-t", "--top", dest="ntop",
                  default='100',
                  help="number of top coherences saved in the datafile", metavar="NumTop")
parser.add_option("-w", "--webtop", dest="wtop",
                  default='20',
                  help="number of top coherences written to the web page", metavar="NumTop")
parser.add_option("-m", "--minfs", dest="minfs",
                  default='32',
                  help="minimum sampling frequency of aux channels", metavar="MinFS")
parser.add_option("-p", "--plot", dest="plotformat",
		  default='png',
		  help="plot format (png, pdf or none)", metavar="PlotFormat")
parser.add_option("-N", "--nproc", dest="ncpu",
		  default='-1',
		  help="number of processes to lauch", metavar="NumProc")

(opt,args) = parser.parse_args()

gpsb = int(opt.gpsb)
gpse = gpsb + int(opt.dt)
dt = int(opt.dt)
outfs = int(opt.outfs)
nav = int(opt.nav)
ntop = int(opt.ntop)
wtop = int(opt.wtop)
minfs = int(opt.minfs)

###### Prepare files for data reading ###############################

print
print "**********************************************************************"
print "**** BruCo version 2015-02-24 - parallelized multicore processing ****"
print "**********************************************************************"
print "Analyzing data from gps %d to %d.\n" % (gpsb, gpse)
print

# determine which are the useful frame files and create the cache
if opt.ifo == '':
	print "Must specify the IFO!"
	exit()

# Create the scratch directory if need be
try:
    os.stat(scratchdir)
    new_scratch = False
except:
    os.mkdir(scratchdir)
    new_scratch = True

# find the location of the GWF files
files = find_LIGO_data(opt.ifo, gpsb, gpsb+dt)

# create the cache file
c = lal.Cache.from_urls(files)
d = frutils.FrameCache(c, scratchdir=scratchdir, verbose=True)

###### Extract the list of channels and remove undesired ones ######################

print ">>>>> Creating chache and extracting list of channels...."
# read the list of channels and sampling rates from the first file
firstfile = c[0].path
os.system('/usr/bin/FrChannels ' + firstfile + ' > bruco.channels')
f = open('bruco.channels')
lines = f.readlines()
channels = []
sample_rate = []
for l in lines:
    ll = l.split()
    if ll[0][1] != '0':
        # remove all L0/H0 channels
        channels.append(ll[0])
        sample_rate.append(int(ll[1]))
channels = array(channels)
sample_rate = array(sample_rate)

# keep only channels with high enough sampling rate
idx = find(sample_rate >= minfs)
channels = channels[idx]
sample_rate = sample_rate[idx]

# load exclusion list from file
f = open(exc, 'r')
L = f.readlines()
excluded = []
for c in L:
    c = c.split()[0]
    excluded.append(c)
f.close()

# delete excluded channels, allowing for unix-shell-like wildcards
idx = ones(shape(channels), dtype='bool')
for c,i in zip(channels, arange(len(channels))):
    for e in excluded:
        if fnmatch.fnmatch(c, opt.ifo + ':' + e):
            idx[i] = False

channels = channels[idx]

# make list unique, removing repeated channels, if any
channels = unique(channels)

# save reduced channel list on textfile, creating the output directory if needed
try:
    os.stat(opt.dir)
except:
    os.mkdir(opt.dir)

f = open(opt.dir + '/channels.txt', 'w')
for c in channels:
    f.write("%s\n" % (c))
f.close()
nch = len(channels)

print "Found %d channels\n\n" % nch

###### Main processing starts here #############################################

print ">>>>> Processing all channels...."

# load the main target channel
buffer = d.fetch(opt.ifo + ':' + opt.channel, gpsb, gpse)
ch1 = numpy.array(buffer)
fs1 = len(ch1) / dt

# number of points per FFT
npoints = pow(2,int(log((gpse - gpsb) * outfs / nav) / log(2)))
print "Number of points = %d\n" % npoints

# compute the main channels FFTs and PSD. Here I save the single segments FFTS, 
# to reuse them later on in the CSD computation. In this way, the main channel FFTs are 
# computed only once, instead of every iteration. This function returns the FFTs already
# scaled is such a way that PSD = sum |FFT|^2, with MATLAB-like normalization.
ch1_ffts = computeFFTs(ch1, npoints*fs1/outfs, (npoints*fs1/outfs)/2, fs1)
psd1 = mean(abs(ch1_ffts)**2,1) 
f1 = linspace(0, fs1/2, npoints*fs1/outfs/2+1)

### Here come some initializations of variables

# create table of top ntop channels for each frequency bin
ntop = int(opt.ntop)
cohtab = zeros((npoints/2+1, ntop))
idxtab = zeros((npoints/2+1, ntop), dtype=int)

# compute the coherence confidence level based on the number of averages used in the PSD
s = scipy.stats.f.ppf(0.95, 2, 2*nav)
s = s/(nav - 1 + s)

##### Here the main loop over all channels begins #####################################

# split the list of channels in as many sublist as there are CPUs
if opt.ncpu == "-1":
    ncpu = multiprocessing.cpu_count()
else:
    ncpui = int(opt.ncpu)
# try the most even possible distribution of channels among the processes
nchannels = len(channels)
n = nchannels / ncpu
N1 = int( (nchannels / float(ncpu) - n) * ncpu)
ch2 = []
chidx = []
for i in range(N1):
    ch2.append(channels[i*(n+1):(i+1)*(n+1)])
    chidx.append(i*(n+1))
for i in range(ncpu-N1):
    ch2.append(channels[N1*(n+1)+i*n:N1*(n+1)+(i+1)*n])
    chidx.append(N1*(n+1)+i*n)

# start a multiprocessing pool
print ">>>>> Starting %d parallel processes..." % ncpu
pool = multiprocessing.Pool()

# Build the list of arguments
args = []
for c,i in zip(ch2,range(len(ch2))):
    args.append([gpsb, gpse, ntop, outfs, npoints, s, opt, ch1_ffts, f1, psd1, c, i, chidx[i]])

# Start all the processes 
results = pool.map(parallelized_coherence, args) 

print ">>>>> Parallel processes finished..."

###### here goes the code to put all results together ####################################

# first step, concatenate the tables
x = zip(*results)
cohtab = concatenate(x[0], axis=1)
idxtab = concatenate(x[1], axis=1)
# then sort in order of descending coherence for each bin
for j in arange(shape(cohtab)[0]):
    ccoh = cohtab[j,:]
    iidx = idxtab[j,:]
    ii = ccoh.argsort()
    cohtab[j, :] = cohtab[j,ii]
    idxtab[j, :] = idxtab[j, ii]
# Finally, keep only the top values, which are the last columns
cohtab = cohtab[:,-ntop:]
idxtab = idxtab[:,-ntop:]

###### Here we save the results to some files in the output directory ####################

# save the coherence tables to files
numpy.savetxt(opt.dir + '/cohtab.txt', cohtab)
numpy.savetxt(opt.dir + '/idxtab.txt', idxtab)

###### And we generate the HTML report #########################################

print ">>>>> Generating report...."

# get list of files, since they corresponds to the list of plots that have been created
command = 'ls %s/*.%s' % (opt.dir, opt.plotformat)
p,g = os.popen4(command)
L = g.readlines()
files = []
for c in L:
    c = (c[:-5]).split('/')[-1]
    files.append(c)

# open web page
page = markup.page( )
page.init( title="Brute force Coherences", \
           footer="(2015)  <a href=mailto:vajente@caltech.edu>vajente@caltech.edu</a>" )


# first section, top channels per frequency bin
nf,nt = shape(cohtab)
freq = linspace(0,outfs/2,nf)

page.h1('Top %d coherences at all frequencies' % wtop)
page.h2('GPS %d (%s) + %d s' % (gpsb, gps2str(gpsb), dt))

page.table(border=1, style='font-size:12px')
page.tr()
page.td(bgcolor="#5dadf1")
page.h3('Frequency [Hz]')
page.td.close()
page.td(colspan=ntop, bgcolor="#5dadf1")
page.h3('Top channels')
page.td.close()
page.tr.close()

# here we create a huge table that contains, for each frequency bin, the list of most coherent
# channels, in descending order. The cell background color is coded from white (no coherence) to
# red (coherence 1)
for i in range(nf):
    page.tr()
    page.td(bgcolor="#5dadf1")
    page.add("%.2f" % freq[i])
    page.td.close()
    for j in range(wtop):
        # write the channel only if the coherence in above the significance level
        if cohtab[i,-(j+1)] > s:
            page.td(bgcolor=cohe_color(cohtab[i,-(j+1)]))
            ch = (channels[int(idxtab[i,-(j+1)])]).split(':')[1]
	    if opt.plotformat != "none":
            	page.add("<a target=_blank href=%s.%s>%s</a><br>(%.2f)" \
                         % (ch, opt.plotformat, newline_name(ch), cohtab[i,-(j+1)]))
	    else:
                page.add("%s<br>(%.2f)" \
                         % (newline_name(ch), cohtab[i,-(j+1)]))
        else:
            page.td(bgcolor=cohe_color(0))

        page.td.close()
    page.tr.close()

page.table.close()

# second section, links to all coherence plots
if len(files)>0:
    page.h1('Coherence with all channels ')
    page.h2('GPS %d (%s) + %d s' % (gpsb, gps2str(gpsb), dt))

    N = len(files)
    m = 6     # number of channels per row
    M = N / m + 1

    page.table(border=1)
    for i in range(M):
        page.tr()
        for j in range(m):
            if i*m+j < N:
                page.td()
                page.add('<a target=_blank href=%s.png>%s</a>' % (files[i*m+j], files[i*m+j]))
                page.td.close()
            else:
                page.td()
                page.td.close()            
    
        page.tr.close()

    page.table.close()
    page.br()

# That's the end, save the HTML page
fileid = open(opt.dir  + '/index.html', 'w')
print >> fileid, page
fileid.close()

if new_scratch:
    os.system("rm -rf %s" % scratchdir)

# Write out some timing statistics
el = time.time() - start_time
print "\n\nTotal elapsed time %d s" % int(el)
