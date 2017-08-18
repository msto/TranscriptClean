
from transcript import Transcript
from spliceJunction import SpliceJunction
from intronBound import IntronBound
from optparse import OptionParser
import pybedtools
from pyfasta import Fasta
import os
import re

def getOptions():
    parser = OptionParser()
    parser.add_option("--f", dest = "sam", help = "Input file",
                      metavar = "FILE", type = "string", default = "")
    parser.add_option("--g", dest = "refGenome", help = "Reference genome fasta file. Should be the same one used to generate the sam file.",
                      metavar = "FILE", type = "string", default = "")
    parser.add_option("--s", dest = "spliceAnnot", help = "Splice junction file obtained by mapping Illumina reads to the genome using STAR. More formats may be supported in the future.",
                      metavar = "FILE", type = "string", default = "")
    parser.add_option("--o", dest = "outfile",
                      help = "output file", metavar = "FILE", type = "string", default = "out")
    (options, args) = parser.parse_args()
    return options

def main():
    options = getOptions()
   
    # Read in the reference genome. Treat coordinates as 0-based 
    print "Reading genome .............................."
    genome = Fasta(options.refGenome)
    #print genome.sequence({'chr': "chr1", 'start': 13221, 'stop': 13224}, one_based=True)
    #exit() 
    print "Processing SAM file ........................."
    header, canTranscripts, noncanTranscripts = processSAM(options.sam, genome)
    print "Processing annotated splice junctions ........"
    annotatedSpliceJns = processSpliceAnnotation(options.spliceAnnot)
    
    cleanMicroindels(canTranscripts, genome)
    cleanMicroindels(noncanTranscripts, genome)

    #print noncanTranscripts["NCTest_Case1"].CIGAR
    #print noncanTranscripts["NCTest_Case1"].SEQ
    #exit()
    cleanNoncanonical(noncanTranscripts, annotatedSpliceJns, genome)
    #print noncanTranscripts["NCTest_Case2"].CIGAR
    #print noncanTranscripts["NCTest_Case2"].SEQ

def processSAM(sam, genome):
    # This function extracts the SAM header (because we'll need that later) and creates a Transcript object for every sam transcript. 
    # Transcripts are returned two separate lists: one canonical and one noncanonical. 

    header = ""
    canTranscripts = {}
    noncanTranscripts = {} 
    with open(sam, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith("@"):
                header = header + line + "\n"
                continue
            t = Transcript(line, genome)
            if t.isCanonical == True:
                canTranscripts[t.QNAME] = t
            else:
                noncanTranscripts[t.QNAME] = t
    return header, canTranscripts, noncanTranscripts

def processSpliceAnnotation(annotFile):
    # This function reads in the tab-separated STAR splice junction file and creates a bedtools object
    
    bedstr = ""
    o = open("tmp.bed", 'w')
    with open(annotFile, 'r') as f:
        for line in f:
            fields = line.strip().split("\t")
            chrom = fields[0]
            start = int(fields[1])
            end = int(fields[2])

            strand = "."
            if fields[3] == "1": strand = "+"
            if fields[3] == "2": strand = "-"
            
            intronMotif = int(fields[4])
            annotated = int(fields[5])
            uniqueReads = fields[6]
            multiReads = fields[7]
            maxOverhang = fields[8]

            # Process only canonical splice junctions or annotated noncanonical junctions
            if (intronMotif != 0) or (intronMotif == 0 and annotated == 1):
                # Make one bed entry for each end of the junction
                bed1 = "\t".join([chrom, str(start - 1), str(start), ".", uniqueReads, strand])
                bed2 = "\t".join([chrom, str(end - 1), str(end), ".", uniqueReads, strand])
                o.write(bed1 + "\n")
                o.write(bed2 + "\n")  
    o.close()
    
    # Convert bed file into BedTool object
    os.system('sort -k1,1 -k2,2n tmp.bed > tmp2.bed')
    bt = pybedtools.BedTool("tmp2.bed")
    return bt

def cleanMicroindels(transcripts, genome):
    # Iterate over transcripts and look for deletions that are <= 5 bp long. 
    # Fix these deletions by adding in the missing reference bases and removing the microindel from the CIGAR string.
    # When removing a deletion from the CIGAR string, attention must be paid to merging the surrounding exon pieces (M). 
    # Therefore, we keep a running count of M length that can be added to the CIGAR string when another operation (N, D > 5, I, S, or H)
    # ends the match.
 
    for t in transcripts.keys():
        t = transcripts[t]
        if "D" in t.CIGAR:
            newCIGAR = ""
            matchTypes, matchCounts = splitCIGAR(t.CIGAR)
            currMVal = 0
            seqIndex = 0
            for operation, count in zip(matchTypes, matchCounts):
                if operation == "D" and count <= 5:
                    t.SEQ = addSeqFromReference(t.SEQ, t.CHROM, t.POS, seqIndex, count, genome)
                    currMVal += count
                    seqIndex += count
                elif operation == "M":
                    currMVal += count
                    
                else:
	            if currMVal > 0:
                        newCIGAR = newCIGAR + str(currMVal) + "M"
                        currMVal = 0
                    newCIGAR = newCIGAR + str(count) + operation
                if operation in ["M", "S", "I"]:                   
                    seqIndex += count
            # Add in any remaining matches 
            if currMVal > 0:
                newCIGAR = newCIGAR + str(currMVal) + "M"
            t.CIGAR = newCIGAR
    return


def cleanNoncanonical(transcripts, annotatedJunctions, genome):
    # Iterate over noncanonical transcripts. Determine whether each end is within 5 basepairs of an annotated junction.
    # If it is, run the rescue function on it. If not, discard the transcript.

    o = open("tmp_nc.bed", 'w')
    salvageableNCJns = 0
    totNC = len(transcripts)
    for tID in transcripts.keys():
        t = transcripts[tID]
        bounds = Transcript.getAllIntronBounds(t)
        
        for b in bounds:
            if b.isCanonical == True:
                continue
            
            # Get BedTool object for start of junction
            pos = IntronBound.getBED(b)
            o.write(pos + "\n")            

    o.close()
    os.system('sort -k1,1 -k2,2n tmp_nc.bed > sorted_tmp_nc.bed')
    nc = pybedtools.BedTool("sorted_tmp_nc.bed")
    jnMatches = str(nc.closest(annotatedJunctions, s=True, D="ref", t="first")).split("\n")
   
    os.system("rm tmp_nc.bed")
    os.system("rm sorted_tmp_nc.bed")
    os.system("rm tmp.bed")
    os.system("rm tmp2.bed")

    # Iterate over splice junction boundaries and their closest canonical match. 
    for match in jnMatches:
        if len(match) == 0: continue
        match = match.split('\t')
        d = int(match[-1])
        transcriptID, spliceJnNum, side = match[3].split("__")
        
        # Only attempt to rescue junction boundaries that are within 5 bp of an annotated junction
        if abs(d) > 5:
            transcripts.pop(transcriptID, None)
            continue
        
        currTranscript = transcripts[transcriptID]
        currJunction = currTranscript.spliceJunctions[int(spliceJnNum)]
        currIntronBound = currJunction.bounds[int(side)]
        rescueNoncanonicalJunction(currTranscript, currJunction, currIntronBound, d, genome)

    return

def rescueNoncanonicalJunction(transcript, spliceJn, intronBound, d, genome):
    # This function converts a noncanonical splice junction to a canonical junction that is <= 5 bp away.
    # To do this, it is necessary to
    # (1) Edit the sam sequence using the reference
    # (2) Potentially change the mapping quality? (Not sure how yet)
    # (3) Change the CIGAR string
    # (4) Change the splice junction intron coordinates (skip for now)
    # (5) Change the splice junction string (skip for now)
   
    correctJunctionSequence(transcript, spliceJn, intronBound, d, genome)
    #correctCIGAR(transcript, spliceJn.jnNumber, intronBound.bound, d)
    #correctJunctionSequence(transcript, spliceJn, intronBound, d, genome)
    #print transcript.QNAME
    #print spliceJn.jnNumber
    #print intronBound
    #print d

    # Be sure to run something to check whether the transcript is now canonical

def correctCIGAR(transcript, targetIntron, intronBound, d):
    # This function modifies the CIGAR string of a transcript to make it reflect the conversion of a particular 
    # splice junction from noncanonical to canonical

    CIGAR = transcript.CIGAR

    # The exon we need to modify depends on which end of the splice junction we are rescuing
    # If we are rescuing the left side, we will modify the exon with the same number as the intron
    # If we are rescuing the right, we will modify exon number intron+1
    targetExon = targetIntron + intronBound

    
    matchTypes, matchCounts = splitCIGAR(CIGAR)
    newCIGAR = ""
    currIntron = 0
    currExon = 0
    for operation,c in zip(matchTypes, matchCounts):
        if operation == "M":   
            if currExon == targetExon:
                if (intronBound == 0 and d > 0) or (intronBound == 1 and d < 0):
                    # Under these conditions, the exon length will increase. Adjust the match count accordingly
                    c = c + abs(d)
                if (intronBound == 0 and d < 0) or (intronBound == 1 and d > 0):
                    # Under these conditions, the exon length will decrease. 
                    c = c - abs(d)
        if operation == "N": 
            if currIntron == targetIntron:
                if (intronBound == 0 and d > 0) or (intronBound == 1 and d < 0):
                    # Under these conditions, the intron length will decrease. Adjust the match count accordingly
                    c = c - abs(d)
                if (intronBound == 0 and d < 0) or (intronBound == 1 and d > 0):
                    # Under these conditions, the intron length will increase. 
                    c = c + abs(d)
            currIntron += 1
            currExon += 1 
        newCIGAR = newCIGAR + str(c) + operation
    # Update the transcript
    transcript.CIGAR = newCIGAR
    return 

def correctJunctionSequence(transcript, spliceJn, intronBound, d, genome):
    # Split up sequence by CIGAR operation, then organize sequence into exon bins accordingly 
    # Then, modify the section needed to make the junction canonical, and concatenate together the new sequence.

    
    seq = transcript.SEQ

    #targetJn = spliceJn.spliceJnNum
    #if intronBound.bound == 0: targetExon = targetJn
    #else: targetExon = targetJn + 1

    currExonStr = ""
    #currGenomePos = transcript.POS
    currSeqIndex = 0
    operations, counts = splitCIGAR(transcript.CIGAR)
    exonSeqs = []
    for op, ct in zip(operations, counts):
        if op == "N":
            exonSeqs.append(currExonStr)
            currExonStr = ""
        elif op in [ "M", "S", "I"]:
            currExonStr = currExonStr + str(seq[currSeqIndex:currSeqIndex+ct])
            currSeqIndex += ct
    exonSeqs.append(currExonStr)
    #print seq    
    print exonSeqs
    #print len(seq)
    #print currSeqIndex

    targetJn = spliceJn.jnNumber
    if intronBound.bound == 0: 
        targetExon = targetJn
        exon = exonSeqs[targetExon]
        if d < 0: # Need to subtract from end of exon sequence. Case 3
            print exonSeqs[targetExon]
            exonSeqs[targetExon] =  exon[0:d]
    #else: targetExon = targetJn + 1
    print ''.join(exonSeqs)

    exit()


def WRONGcorrectJunctionSequence(transcript, spliceJn, intronBound, d, genome):
    # Given a transcript, a splice junction location, and the end of the splice junction to edit, this function adds or subtracts d bases (as appropriate),
    # drawing them from the reference genome

    seq = transcript.SEQ
    newSeq = seq
    # Case 1: The exon ended too early. Add d bases to the end of the exon. intronBound = 0 and d > 0
    if intronBound.bound == 0 and d > 0:
        exonEnd = intronBound.pos - 1
        # Figure out which position in the seq string is exonEnd
        seqIndex = exonEnd - transcript.POS + 1
        newSeq = addSeqFromReference(seq, transcript.CHROM, transcript.POS, seqIndex, d, genome)
        intronBound.pos += d
        spliceJn.end = intronBound.pos

    # Case 2: The exon started too late. Add d bases to the beginning of the exon. intronBound = 1 and d < 0
    elif intronBound.bound == 1 and d < 0:
        exonStart = intronBound.pos + 1 
        seqIndex = exonStart - transcript.POS + 1
        newSeq = addSeqFromReference(seq, transcript.CHROM, transcript.POS, seqIndex, d, genome)
        intronBound.pos -= d
        spliceJn.start = intronBound.pos

    # Case 3: The exon ended too late. Remove d bases from the end of the exon
    elif intronBound.bound == 0 and d < 0:
        exonEnd = intronBound.pos - 1
        seqIndex = exonEnd - transcript.POS + d + 1
        newSeq = seq[0:seqIndex] + seq[seqIndex + abs(d):]
        intronBound.pos -= d
        spliceJn.end = intronBound.pos

    # Case 4: The exon started too early. Remove d bases from the beginning of the exon
    elif intronBound.bound == 1 and d > 0: 
        exonStart = intronBound.pos - 1
        seqIndex = exonStart - transcript.POS + 1 - d
        newSeq = seq[0:seqIndex] + seq[seqIndex + 1:]
        intronBound.pos += d
        spliceJn.end = intronBound.pos
    transcript.SEQ = newSeq
    #print intronBound.pos
    return
 
def splitCIGAR(CIGAR):
    # Takes CIGAR string from SAM and splits it into two lists: one with capital letters (match operators), and one with the number of bases

    matchTypes = re.sub('[0-9]', " ", CIGAR).split()
    matchCounts = re.sub('[A-Z]', " ", CIGAR).split()
    matchCounts = [int(i) for i in matchCounts]

    return matchTypes, matchCounts


def addSeqFromReference(seq, chrom, tStart, seqIndex, nBases, genome):
    # This function inserts n reference bases into a transcript sequence at the point where seqIndex bases have come before in the original sequence.
    # Because Python is zero-based, this means that the bases will be inserted right BEFORE string index == seqIndex
    seqStart = seq[0:seqIndex]
    seqEnd =  seq[seqIndex:]

    refStart = tStart + seqIndex
    insert = genome.sequence({'chr': chrom, 'start': refStart, 'stop': refStart + nBases - 1}, one_based=True)
    newSeq = seqStart + insert + seqEnd
    return newSeq 
    
main()
