# create or recreate conda environment called blinder with python version 3.10
conda deactivate
conda env remove -n blinder
conda create -n blinder python=3.10

# install each requirements.txt in each src/* folder
for d in src/*; do
    if [ -d "$d" ]; then
        echo "Installing requirements for $d..."
        pip install -r $d/requirements.txt
    fi
done

# install pre-commit hooks
pre-commit install