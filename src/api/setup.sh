# create or recreate conda environment called aggy with python version 3.10
conda deactivate
# delete and remove all packages from existing env is it exists
conda remove -n aggy --all -y
conda create -n -y aggy python=3.10
conda activate aggy

pip install -r requirements.txt

# install pre-commit hooks
pre-commit install
