import pytest
from pyfasta import Fasta
import sys
sys.path.append("..")
import transcript2 as t2
import spliceJunction as sj
import intronBound as ib
import TranscriptClean as TC
import dstruct as dstruct
@pytest.mark.unit

class TestAttemptJnCorrection(object):

    def test_too_far_away(self):
        """ A case where the NCSJ should not be corrected because it is too far
            away from the closest annotated junction relative to the maxDist
            parameter.
     
         Toy transcript with sequence A|GAA, where the splice motif
            is noncanonical.
            chr1: 23,071,357 - 23,072,126 
        """

        # Process references
        sjFile = "input_files/test_junctions.txt"
        outprefix = "scratch/test"
        donors, acceptors, sjDict = TC.processSpliceAnnotation(sjFile, outprefix)
        genome = Fasta("input_files/hg38_chr1.fa")


        # Init transcript object
        sam_fields = "\t".join(["test_read", "0", "chr1", "23071357", "255", "1M766N3M", "*",
                      "0", "0", "AGAA", "*",  "NM:i:0", "MD:Z:6"])
        transcript = t2.Transcript2(sam_fields, genome, sjDict)
        jnNumber = 0
        maxDist = 1

        correction_status, reason, dist = TC.attempt_jn_correction(transcript, 
                                                                   jnNumber, 
                                                                   donors, 
                                                                   acceptors,
                                                                   maxDist)
        assert correction_status == False
        assert reason == "TooFarFromAnnotJn"
        assert dist == 2 
        
         
