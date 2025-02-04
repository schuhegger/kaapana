import os
import json
import numpy as np
import nibabel as nib
from datetime import timedelta
from multiprocessing.pool import ThreadPool
from glob import glob
from os.path import join, basename, dirname, exists
from pathlib import Path
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
from kaapana.operators.KaapanaPythonBaseOperator import KaapanaPythonBaseOperator
from matplotlib import rcParams
rcParams.update({'figure.autolayout': True})
class LocalDiceOperator(KaapanaPythonBaseOperator):
    def create_plots(self, result_dir, result_table):
        print(f"# Creating boxplots @: {result_dir}")
        os.makedirs(result_dir, exist_ok=True)
        df_data = pd.DataFrame(result_table, columns=['Series', 'Model', 'label', 'Dice'])
        new_order = sorted(list(df_data.Model.unique()))
        new_order.append(new_order.pop(new_order.index('ensemble')))
        fig, ax1 = plt.subplots(1, 1, figsize=(12, 14))
        box_plot = sns.boxplot(x="Model", y="Dice", hue="label", palette="Set3", data=df_data, ax=ax1,order=new_order)
        box_plot.set_xticklabels(box_plot.get_xticklabels(), rotation=40, ha="right")

        box = box_plot.get_position()
        box_plot.set_position([box.x0, box.y0, box.width * 0.85, box.height])  # resize position
        box_plot.legend(loc='center right', bbox_to_anchor=(1.22, 0.5), ncol=1)
        plt.tight_layout()
        fig.savefig(join(result_dir, "dice_results.pdf"))
        fig.savefig(join(result_dir, "dice_results.png"), dpi=fig.dpi)
        print("# DONE")

    def get_model_infos(self, model_batch_dir):
        model_batch_dir = join(model_batch_dir, "model-exports")
        print(f"# Searching for dataset.json @: {model_batch_dir}")
        labels = None
        model_id = None
        model_info = glob(join(model_batch_dir, "**", "dataset.json"), recursive=True)
        if len(model_info) == 0:
            print("# Could not find any dataset.json !")
        elif len(model_info) > 1:
            print("# Found multiple dataset.json !")
        else:
            assert len(model_info) == 1
            with open(model_info[0]) as f:
                dataset_json = json.load(f)
            labels = dataset_json["labels"]
            model_id = dataset_json["name"]

        return labels, model_id

    def get_pred_infos(self, pred_dir):
        print(f"# Searching for seg_info.json @: {pred_dir}")
        seg_info = glob(join(pred_dir, "**", "seg_info.json"), recursive=True)
        labels = None
        model_id = None

        if len(seg_info) != 1:
            print(f"# Could not find seg_info.json (found {len(seg_info) }) !")
            return None, None
        else:
            with open(seg_info[0]) as f:
                seg_info = json.load(f)
            labels = {}
            for label in seg_info["seg_info"]:
                labels[label["label_int"]] = label["label_name"]

            model_id = seg_info["task_id"]

        return labels, model_id

    def prep_nifti(self, nifti_path):
        nifti_numpy = nib.load(nifti_path).get_fdata().astype(int)
        nifti_labels = list(np.unique(nifti_numpy))

        if 0 in nifti_labels:
            nifti_labels.remove(0)
        else:
            print("#")
            print(f"# Couldn't find a 'Clear Label' 0 in NIFTI!")
            print(f"# NIFTI-path: {nifti_path}")
            print("#")
            exit(1)

        return nifti_numpy, nifti_labels

    def calc_dice(self, pred, gt, empty_score=1.0):
        pred = np.asarray(pred).astype(bool)
        gt = np.asarray(gt).astype(bool)

        if pred.shape != gt.shape:
            print("#")
            print("##################################################")
            print("#")
            print("#################  ERROR  #######################")
            print("#")
            print("# ----> SHAPE MISMATCH!")
            print(f"# gt:   {gt.shape}")
            print(f"# pred: {pred.shape}")
            print("#")
            print("#")
            print("##################################################")
            print("#")
            raise ValueError("Shape mismatch: pred and gt must have the same shape.")

        im_sum = pred.sum() + gt.sum()
        if im_sum == 0:
            return empty_score

        # Compute Dice coefficient
        intersection = np.logical_and(pred, gt)

        return 2. * intersection.sum() / im_sum

    def start(self, ds, **kwargs):
        print("# Evaluating predictions started ...")
        print(f"# workflow_dir {self.workflow_dir}")
        self.anonymize_lookup_table = {}
        model_counter = 0
        case_counter = 0

        result_scores_case_based = {}
        result_scores_model_based = {}
        result_table = []

        run_dir = os.path.join(self.workflow_dir, kwargs['dag_run'].run_id)
        processed_count = 0
        if self.ensemble_dir != None:
            self.ensemble_dir = join(run_dir, self.ensemble_dir)
            if not exists(self.ensemble_dir):
                print("# Could not find ensemble_pred_dir !")
                print(f"# pred: {self.ensemble_dir}")
                exit(1)

        batch_folders = [f for f in glob(os.path.join(run_dir, self.batch_name, '*'))]
        print("# Found {} batches".format(len(batch_folders)))
        for batch_element_dir in batch_folders:
            print(f"# processing batch-element: {batch_element_dir}")
            model_counter += 1
            single_model_pred_dir = join(batch_element_dir, self.operator_in_dir)
            labels, model_id = self.get_pred_infos(pred_dir=single_model_pred_dir)
            if labels == None or model_id == None:
                labels, model_id = self.get_model_infos(model_batch_dir=batch_element_dir)
            model_id = f"{model_id}_{model_counter}"

            single_model_pred_files = sorted(glob(join(single_model_pred_dir, "*.nii*"), recursive=False))
            for single_model_pred_file in single_model_pred_files:
                case_counter += 1
                ensemble_already_processed = False
                file_id = basename(single_model_pred_file).replace(".nii.gz", "")

                gt_file = join(run_dir, "nnunet-cohort", file_id, self.gt_dir, basename(single_model_pred_file))
                if not exists(gt_file):
                    print("# Could not find gt-file !")
                    print(f"# gt:   {gt_file}")
                    exit(1)
                if self.anonymize:
                    if file_id not in self.anonymize_lookup_table:
                        self.anonymize_lookup_table[file_id] = f"case_{case_counter}"
                    file_id = self.anonymize_lookup_table[file_id]

                # result_scores_sm[model_id][file_id]["gt_file"] = gt_file
                # result_scores_sm[model_id][file_id]["pred_file"] = single_model_pred_file
                print(f"# Loading gt-file: {gt_file}")
                gt_numpy, gt_labels = self.prep_nifti(gt_file)
                print(f"# Loading model-file: {single_model_pred_file}")
                sm_numpy, sm_labels = self.prep_nifti(single_model_pred_file)
                print("#")
                print(f"# gt_labels:   {gt_labels}")
                print(f"# pred_labels: {sm_labels}")
                print("#")

                print(f"# Loading labels...")
                for pred_label in sm_labels:
                    print(f"# label: {pred_label}")
                    label_key = labels[str(pred_label)] if labels != None and str(pred_label) in labels else None
                    print(f"# label_key: {label_key}")
                    if label_key == None and labels != None:
                        print("##################################################")
                        print("#")
                        print("##################### INFO ######################")
                        print("#")
                        print(f"# predicted label {pred_label}: {label_key} can't be found!")
                        print(f"# labels: {labels}")
                        print("#")
                        print("##################################################")
                        # assert pred_label in gt_labels
                    else:
                        label_strip_gt = (gt_numpy == pred_label).astype(int)
                        label_strip_sm = (sm_numpy == pred_label).astype(int)
                        dice_result = self.calc_dice(pred=label_strip_sm, gt=label_strip_gt)

                        print(f"# Adding dataset: {file_id}/{model_id}/{label_key}/{dice_result}")
                        result_table.append([
                            file_id,
                            model_id,
                            label_key,
                            dice_result
                        ])

                        if model_id not in result_scores_model_based:
                            result_scores_model_based[model_id] = {}
                        if label_key not in result_scores_model_based[model_id]:
                            result_scores_model_based[model_id][label_key] = {}
                        result_scores_model_based[model_id][label_key][file_id] = dice_result

                        if file_id not in result_scores_case_based:
                            result_scores_case_based[file_id] = {}
                        if label_key not in result_scores_case_based[file_id]:
                            result_scores_case_based[file_id][label_key] = {}
                        result_scores_case_based[file_id][label_key][model_id] = dice_result

                        # print(f"# {str(pred_label)}:{label_key} -> dice: {dice_result}")
                        if "ensemble" in result_scores_case_based[file_id][label_key]:
                            ensemble_already_processed = True
                print("#")

                ensemble_numyp = None
                ensemble_labels = None
                if self.ensemble_dir != None and not ensemble_already_processed:
                    print("# Ensemble prediction...")
                    print("#")
                    ensemble_file = join(self.ensemble_dir, basename(single_model_pred_file))
                    ensemble_numyp, ensemble_labels = self.prep_nifti(ensemble_file)
                    model_id_ensemble = "ensemble"
                    for pred_label in ensemble_labels:
                        label_key = labels[str(pred_label)] if str(pred_label) in labels else str(pred_label)
                        if label_key == None and labels != None:
                            print("##################################################")
                            print("#")
                            print("##################### INFO ######################")
                            print("#")
                            print(f"# predicted label {pred_label}: {label_key} can't be found!")
                            print(f"# labels: {labels}")
                            print("#")
                            print("##################################################")
                            # assert pred_label in gt_labels
                        else:
                            label_strip_gt = (gt_numpy == pred_label).astype(int)
                            label_strip_ensemble = (ensemble_numyp == pred_label).astype(int)
                            dice_result = self.calc_dice(pred=label_strip_ensemble, gt=label_strip_gt)
                            # print(f"# {str(pred_label)}:{label_key} -> dice: {dice_result}")
                            print(f"# Adding ensemble: {file_id}/{model_id_ensemble}/{label_key}/{dice_result}")
                            result_table.append([
                                file_id,
                                model_id_ensemble,
                                label_key,
                                dice_result
                            ])

                            if file_id not in result_scores_case_based:
                                result_scores_case_based[file_id] = {}
                            if label_key not in result_scores_case_based[file_id]:
                                result_scores_case_based[file_id][label_key] = {}
                            result_scores_case_based[file_id][label_key][model_id_ensemble] = dice_result
                    print("#")

                processed_count += 1
                print("##################################################")

        print("# ")
        print("# RESULTS: ")
        print("# ")
        print(json.dumps(result_scores_case_based, indent=4, sort_keys=True, default=str))
        print("# ")
        print("#")
        print(f"# Processed file_count: {processed_count}")
        print("#")
        print("#")
        result_dir = join(run_dir, self.operator_out_dir)
        Path(result_dir).mkdir(parents=True, exist_ok=True)

        result_ensemble_path = os.path.join(result_dir, "results_case_based.json")
        with open(result_ensemble_path, 'w+', encoding='utf-8') as f:
            json.dump(result_scores_case_based, f, ensure_ascii=False, default=str, indent=4, sort_keys=True)

        result_ensemble_path = os.path.join(result_dir, "results_model_based.json")
        with open(result_ensemble_path, 'w+', encoding='utf-8') as f:
            json.dump(result_scores_model_based, f, ensure_ascii=False, default=str, indent=4, sort_keys=True)

        self.create_plots(result_dir=result_dir, result_table=result_table)

        if processed_count == 0:
            print("#")
            print("##################################################")
            print("#")
            print("#################  ERROR  #######################")
            print("#")
            print("# ----> NO FILES HAVE BEEN PROCESSED!")
            print("#")
            print("##################################################")
            print("#")
            exit(1)
        else:
            print("# DONE #")

    def __init__(self,
                 dag,
                 gt_operator,
                 ensemble_operator=None,
                 batch_name=None,
                 workflow_dir=None,
                 anonymize=True,
                 *args,
                 **kwargs):

        self.gt_dir = gt_operator.operator_out_dir
        self.ensemble_dir = ensemble_operator.operator_out_dir if ensemble_operator != None else None
        self.anonymize = anonymize

        super().__init__(
            dag,
            name="dice-eval",
            python_callable=self.start,
            batch_name=batch_name,
            workflow_dir=workflow_dir,
            execution_timeout=timedelta(minutes=20),
            *args,
            **kwargs
        )
