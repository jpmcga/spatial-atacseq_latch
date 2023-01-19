from enum import Enum
import os
from pathlib import Path
import subprocess

from latch import large_task, workflow
from latch.resources.launch_plan import LaunchPlan
from latch.types import (LatchAuthor, LatchDir, LatchFile, LatchMetadata,
                        LatchParameter, LatchRule)


class Species(Enum):
    mouse = "refdata-cellranger-arc-mm10-2020-A-2.0.0"
    human = "refdata-cellranger-arc-GRCh38-2020-A-2.0.0"


@large_task(retries=0)
def filter_task(
    r1: LatchFile,
    r2: LatchFile,
    run_id: str
) -> (LatchFile, LatchFile):

    filtered_r1_l1 = Path(f"{run_id}_linker1_R1.fastq.gz").resolve()
    filtered_r2_l1 = Path(f"{run_id}_linker1_R2.fastq.gz").resolve()

    _bbduk1_cmd = [
        "bbmap/bbduk.sh",
        # "-Xmx100g", 
        # "-Xms100g",
        f"in1={r1.local_path}",
        f"in2={r2.local_path}",
        f"outm1={str(filtered_r1_l1)}",
        f"outm2={str(filtered_r2_l1)}",
        "skipr1=t",
        "k=30",
        "mm=f",
        "rcomp=f",
        "restrictleft=103",
        "hdist=3",
        f"stats=/root/{run_id}_linker1_stats.txt",
        "threads=86", # 80% does this matter?
        "literal=GTGGCCGATGTTTCGCATCGGCGTACGACT"
        ]

    subprocess.run(_bbduk1_cmd)

    filtered_r1_l2 = Path(f"{run_id}_linker2_R1.fastq.gz").resolve()
    filtered_r2_l2 = Path(f"{run_id}_linker2_R2.fastq.gz").resolve()

    _bbduk2_cmd = [
        "bbmap/bbduk.sh",
        f"in1={str(filtered_r1_l1)}",
        f"in2={str(filtered_r2_l1)}",
        f"outm1={str(filtered_r1_l2)}",
        f"outm2={str(filtered_r2_l2)}",
        "skipr1=t",
        "k=30",
        "mm=f",
        "rcomp=f",
        "restrictleft=65",
        "hdist=3",
        f"stats=/root/{run_id}_linker2_stats.txt",
        "threads=46",
        "literal=ATCCACGTGCTTGAGAGGCCAGAGCATTCG"
    ]

    subprocess.run(_bbduk2_cmd)

    return (
            LatchFile(
                str(filtered_r1_l2),
                f"latch:///runs/{run_id}/cellranger_inputs/{run_id}_S1_L001_R1_001.fastq.gz"
        ),
            LatchFile(
                str(filtered_r2_l2),
                f"latch:///runs/{run_id}/preprocessing/{run_id}_linker2_R2.fastq.gz"
        )
    )


@large_task(retries=0)
def process_bc_task(
    r2: LatchFile,
    run_id: str
) -> (LatchDir):
    """ Process read2: save genomic portion as read3, extract 16 bp
    barcode seqs and save as read3
    """

    outdir = Path("cellranger_inputs/").resolve()
    os.mkdir(outdir)
    new_r2 = Path(f"{outdir}/{run_id}_S1_L001_R2_001.fastq").resolve()
    r3 = Path(f"{outdir}/{run_id}_S1_L001_R3_001.fastq").resolve()

    _bc_cmd = [
        "python",
        "bc_process.py",
        "--input",
        r2.local_path,
        "--output_R2",
        f"{str(new_r2)}",
        "--output_R3",
        f"{str(r3)}"
    ]

    subprocess.run(_bc_cmd)

    return LatchDir(
        str(outdir),
        f"latch:///runs/{run_id}/cellranger_inputs/"
    )


@large_task(retries=0)
def cellranger_task(
    input_dir: LatchDir,
    run_id: str,
    species: Species
) -> (LatchDir):

    local_out = Path(f'{run_id}/outs/').resolve()

    _cr_command = [
    "cellranger-atac-2.1.0/cellranger-atac",
    "count",
    f"--id={run_id}", 
    f"--reference={species.value}",
    f"--fastqs={input_dir.local_path}",
    "--localcores=96",
    "--localmem=192",
    "--force-cells=2500",
    ]

    subprocess.run(cr_command)

    return LatchDir(
        str(local_out),
        f"latch:///runs/{run_id}/outs/"
    )


metadata = LatchMetadata(
    display_name="Spatial ATAC-seq",
    author=LatchAuthor(
        name="James McGann",
        email="jpaulmcgann@gmail.com",
        github="github.com/jpmcga",
    ),
    repository="https://github.com/jpmcga/spatial-atacseq_latch/",
    parameters={
        "r1": LatchParameter(
            display_name="read 1",
            description="Read 1 must contain genomic sequence.",
            batch_table_column=True,
        ),
        "r2": LatchParameter(
            display_name="read 2",
            description="Read 2 must contain barcode sequences \
                        and end with >35bp of genomic sequence.",
            batch_table_column=True,
        ),
        "run_id": LatchParameter(
            display_name="run id",
            description="ATX Run ID, default to Dxxxxx_NGxxxxx format; must match fastqs.",
            batch_table_column=True,
            placeholder="Dxxxxx_NGxxxxx",
            comment="Must match prefix of input fastq (Dxxxxx_NGxxxxx)",
            rules=[
                LatchRule(
                    regex="^(D\d{5}_NG\d{5})$",
                    message="Must match prefix of input fastq (Dxxxxx_NGxxxxx)"
                )
            ]
        ),
        "species": LatchParameter(
            display_name="species",
            description="Select reference genome for cellranger atac.",
            batch_table_column=True,
        ),
    },
)


@workflow(metadata)
def spatial_atac(
    r1: LatchFile,
    r2: LatchFile,
    run_id: str,
    species: Species
) -> (LatchDir):
    """Pipeline for processing Spatial ATAC-seq data generated via DBiT-seq.

    Spatial ATAC-seq
    ----

    Process data from DBiT-seq experiments for spatially-resolved epigenomics:

    > See Deng, Y. et al 2022.

    # Steps

    * filter read2 on linker 1 identify via bbduk
    * filter read2 on linker 2 identify via bbduk
    * split read2 into genomic (read3) and barcode (read2)
    * run Cell Ranger ATAC
    """

    filtered_r1, filtered_r2 = filter_task(r1=r1, r2=r2, run_id=run_id)
    input_dir = process_bc_task(r2=filtered_r2, run_id=run_id)
    return cellranger_task(input_dir=input_dir, run_id=run_id, species=species)


LaunchPlan(
    spatial_atac,
    "Test Data",
    {
        "r1" : LatchFile("latch:///BASESPACE_IMPORTS/projects/PL000121/D01033_NG01681_L1/D01033_NG01681_S3_L001_R1_001.fastq.gz"),
        "r2" : LatchFile("latch:///BASESPACE_IMPORTS/projects/PL000121/D01033_NG01681_L1/D01033_NG01681_S3_L001_R2_001.fastq.gz"),
        "run_id" : "D01033_NG01681",
        "species" : Species.human
    },
)
