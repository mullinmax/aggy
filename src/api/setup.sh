# create or recreate conda environment called blinder with python version 3.10
conda deactivate
# delete and remove all packages from existing env is it exists
conda remove -n blinder --all -y
conda create -n -y blinder python=3.10
conda activate blinder

pip install -r requirements.txt

# install pre-commit hooks
pre-commit install
