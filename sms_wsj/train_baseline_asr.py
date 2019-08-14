import os
from pathlib import Path

import sacred
from paderbox.database import JsonDatabase
from paderbox.utils.process_caller import run_process
from sms_wsj.kaldi.utils import create_data_dir, create_kaldi_dir
import shutil

kaldi_root = Path(os.environ['KALDI_ROOT'])
assert kaldi_root.exists(), (
    f'The environmental variable KALDI_ROOT has to be set to a working kaldi'
    f' root, at the moment it points to f{kaldi_root}'
)
assert (kaldi_root / 'src').exists(), (
    f'The environmental variable KALDI_ROOT has to be set to a working kaldi'
    f' root, at the moment it points to f{kaldi_root}'
)
assert (kaldi_root / 'src' / 'base' / '.depend.mk').exists(), (
    'The kaldi your KALDI_ROOT points to is not installed, please refer to'
    ' kaldi for further information on how to install it'
)
ex = sacred.Experiment('Kaldi ASR baseline training')


@ex.config
def config():
    egs_path = None
    json_path = None
    if 'CCS_NODEFILE' in os.environ:
        num_jobs = len(list(
            Path(os.environ['CCS_NODEFILE']).read_text().strip().splitlines()
        ))
    else:
        num_jobs = os.cpu_count()
    stage = 0
    end_stage = 20
    kaldi_cmd = 'run.pl'
    ali_data_type = 'sms_early'
    train_data_type = 'sms_single'
    gmm_dir = None
    # ToDo: change to kaldi_root/egs/ if no egs_path is defined?
    assert egs_path is not None, \
        'The directory where all asr training related data is stored has' \
        ' to be defined, use "with storage_dir=/path/to/storage/dir"'
    assert json_path is not None, \
        'The path to the json describing the SMS-WSJ database has to be' \
        ' defined, use "with json_path=/path/to/json/sms_wsj.json"' \
        ' (for creating the json use ...)'


@ex.automain
def run(_config, egs_path, json_path, stage, end_stage, gmm_dir,
        ali_data_type, train_data_type, kaldi_cmd, num_jobs):
    sms_db = JsonDatabase(json_path)
    sms_kaldi_dir = Path(egs_path).resolve().expanduser() / train_data_type / 's5'
    if stage <= 1 < end_stage:
        create_kaldi_dir(sms_kaldi_dir)

    if kaldi_cmd == 'ssh.pl':
        CCS_NODEFILE = Path(os.environ['CCS_NODEFILE'])
        if (sms_kaldi_dir / '.queue').exists():
            print('Deleting already existing .queue directory')
            shutil.rmtree(sms_kaldi_dir / '.queue')
        (sms_kaldi_dir / '.queue').mkdir()
        (sms_kaldi_dir / '.queue' / 'machines').write_text(CCS_NODEFILE.read_text())
        with (sms_kaldi_dir / 'cmd.sh').open('a') as fd:
            fd.writelines('export train_cmd="ssh.pl"')
    elif kaldi_cmd == 'run.pl':
        with (sms_kaldi_dir / 'cmd.sh').open('a') as fd:
            fd.writelines('export train_cmd="run.pl"')
    else:
        raise ValueError(kaldi_cmd)

    if gmm_dir is None:
        gmm = 'tri4b'
    else:
        gmm_dir = Path(gmm_dir)
        gmm = gmm_dir.name
    if stage <= 2 < end_stage:
        if gmm_dir is None:
            create_data_dir(sms_kaldi_dir, db=sms_db, data_type='wsj_8k')
            print('Start training tri3 model on wsj_8k')
            run_process([
                f'{sms_kaldi_dir}/local_sms/get_tri3_model.bash',
                '--dest_dir', f'{sms_kaldi_dir}',
                '--nj', str(num_jobs)],
                cwd=str(sms_kaldi_dir),
                stdout=None, stderr=None
            )
        else:
            assert gmm_dir.exists()
            gmm_parent_dir = sms_kaldi_dir / 'exp' / 'wsj_8k'
            gmm_parent_dir.mkdir(parents=True)
            shutil.copytree(gmm_dir,  gmm_parent_dir / gmm)

    if stage <= 3 < end_stage and not ali_data_type == train_data_type:
        create_data_dir(sms_kaldi_dir, db=sms_db, data_type=ali_data_type,
                        ref_channels=[0, 1, 2, 3, 4, 5])

    if stage <= 4 < end_stage:
        create_data_dir(
            sms_kaldi_dir, db=sms_db, data_type=train_data_type,
            ref_channels=[0, 1, 2, 3, 4, 5]
        )

    if stage <= 16 < end_stage:
        print('Prepare data for nnet3 model training on sms_wsj')
        run_process([
            f'{sms_kaldi_dir}/local_sms/prepare_nnet3_model_training.bash',
            '--dest_dir', f'{sms_kaldi_dir}',
            '--cv_sets', "cv_dev93",
            '--stage', str(stage),
            '--gmm_data_type', 'wsj_8k',
            '--gmm', gmm,
            '--ali_data_type', ali_data_type,
            '--dataset', train_data_type,
            '--nj', str(num_jobs)],
            cwd=str(sms_kaldi_dir),
            stdout=None, stderr=None
        )

    if stage <= 17:
        print('Start training nnet3 model on sms_wsj')
        run_process([
            f'{sms_kaldi_dir}/local_sms/get_nnet3_model.bash',
            '--dest_dir', f'{sms_kaldi_dir}',
            '--cv_sets', '"cv_dev93"',
            '--stage', str(stage),
            '--gmm_data_type', 'wsj_8k',
            '--gmm', gmm,
            '--ali_data_type', ali_data_type,
            '--dataset', train_data_type,
            '--nj', str(num_jobs)],
            cwd=str(sms_kaldi_dir),
            stdout=None, stderr=None
        )
