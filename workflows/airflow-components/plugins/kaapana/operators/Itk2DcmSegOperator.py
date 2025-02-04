
from datetime import datetime
from datetime import timedelta
from kaapana.operators.KaapanaBaseOperator import KaapanaBaseOperator, default_registry, default_project

class Itk2DcmSegOperator(KaapanaBaseOperator):

    def __init__(self,
                 dag,
                 segmentation_operator,
                 input_type='single_label_segs',
                 alg_name= None,
                 creator_name="kaapana",
                 alg_type="AUTOMATIC",
                 single_label_seg_info=None,
                 create_multi_label_dcm_from_single_label_segs=False,
                 multi_label_seg_info_json=None,          
                 multi_label_seg_name=None,
                 series_description=None,
                 skip_empty_slices=False,
                 env_vars=None,
                 execution_timeout=timedelta(minutes=90),
                 *args,
                 **kwargs):

        if env_vars is None:
            env_vars = {}

        envs = {
            "INPUT_TYPE": input_type,  # multi_label_seg or single_label_segs
            # Relevant if input is single label seg objects or multiple single label seg objects
            "SINGLE_LABEL_SEG_INFO": single_label_seg_info, # SINGLE_LABEL_SEG_INFO must be either "from_file_name" or a e.g. "right@kidney"
            "CREATE_MULIT_LABEL_DCM_FROM_SINGLE_LABEL_SEGS": str(create_multi_label_dcm_from_single_label_segs), # true or false
            # Relevant if input is multilabel seg object
            "MULTI_LABEL_SEG_INFO_JSON": multi_label_seg_info_json, # name of json file inside OPERATOR_IMAGE_LIST_INPUT_DIR that contains the organ seg infos e.g. {"seg_info": ["spleen", "right@kidney"]}
            # Always relevant:
            "MULTI_LABEL_SEG_NAME": multi_label_seg_name,  # Name used for multi-label segmentation object, if it will be created
            "OPERATOR_IMAGE_LIST_INPUT_DIR":  segmentation_operator.operator_out_dir, # directory that contains segmentaiton objects
            "SERIES_DISCRIPTION": "{}".format(series_description or alg_name or 'UNKOWN SEGMENTATION ALGORITHM'),
            "ALGORITHM_NAME": f'{alg_name or "kaapana"}',
            "CREATOR_NAME": creator_name,
            "ALGORITHM_TYPE": alg_type,
            "SERIES_NUMBER": "300",
            "INSTANCE_NUMBER": "1",
            "SKIP_EMPTY_SLICES": f"{skip_empty_slices}",
            "DCMQI_COMMAND": 'itkimage2segimage'
        }
        env_vars.update(envs)

        super().__init__(
            dag=dag,
            image="{}{}/dcmqi:v1.2.3-vdev".format(default_registry, default_project),
            name="nrrd2dcmseg",
            env_vars=env_vars,
            image_pull_secrets=["registry-secret"],
            execution_timeout=execution_timeout,
            ram_mem_mb=3000,
            ram_mem_mb_lmt=6000,
            *args,
            **kwargs
            )
