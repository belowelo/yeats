---
title: "RNA-seq assembler artifacts can bias expression counts and differential expression analysis - application of YeATS on the chickpea transcriptome"
authors: ["Sandeep Chakraborty"]
year: 2016
source: "angl"
doi: "https://doi.org/10.12688/f1000research.9667.1"
journal: "F1000Research"
strand: ""  # filled by 05_lda_strands.py
works_discussed: []  # filled by 04_subject_assign.py
---

## Abstract

<ns4:p> <ns4:bold>Background</ns4:bold> : The unprecedented volume of genomic and transcriptomic data analyzed by software pipelines makes verification of inferences based on such data, albeit theoretically possible, a challenging proposition. The availability of intermediate data can immensely aid re-validation efforts. One such example is the transcriptome, assembled from raw RNA-seq reads, which is frequently used for annotation and quantification of genes transcribed. The quality of the assembled transcripts influences the accuracy of inferences based on them. </ns4:p> <ns4:p> <ns4:bold>Method</ns4:bold> : Here the publicly available transcriptome from Cicer arietinum (ICC4958; Desi chickpea, <ns4:ext-link xmlns:ns3="http://www.w3.org/1999/xlink" ext-link-type="uri" ns3:href="http://www.nipgr.res.in/ctdb.html">http://www.nipgr.res.in/ctdb.html</ns4:ext-link> ) was analyzed using YeATS. </ns4:p> <ns4:p> <ns4:bold>Results and Conclusion</ns4:bold> : The analysis revealed that a majority of the highly expressed transcripts (HET) encoded multiple genes, strongly indicating that the counts may have been biased by the merging of different transcripts. TC00004 is ranked in the top five HET for all five tissues analyzed here, and encodes both a retinoblastoma-binding-like protein (E-value=0) and a senescence-associated protein (E-value= 5e-108). Fragmented transcripts are another source of error. The ribulose bisphosphate carboxylase small chain (RBCSC) protein is split into two transcripts with an overlapping amino acid sequence "ASNGGRVHC", TC13991 and TC23009, with length 201 and 332 nucleotides and expression counts 17.90 and 1403.8, respectively. </ns4:p> <ns4:p>The huge difference in counts indicates an erroneous normalization algorithm in determining counts. It is well known that RBCSC is highly expressed and expectedly TC23009 ranks fifth among HETs in the shoot. Furthermore, some transcripts are split into open reading frames that map to the same protein, although this should not have any significant bearing on the counts. It is proposed that studies analyzing differential expression based on the transcriptome should consider these artifacts, and providing intermediate assembled transcriptomes should be mandatory, possibly with a link to the raw sequence data (Bioproject).</ns4:p>


## Links

*Works discussed will be linked by `04_subject_assign.py`.*
