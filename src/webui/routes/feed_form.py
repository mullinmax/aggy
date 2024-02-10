from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectMultipleField
from wtforms.validators import DataRequired, URL

class FeedForm(FlaskForm):
    name = StringField('Feed Name', validators=[DataRequired()])
    url = StringField('RSS URL', validators=[DataRequired(), URL()])
    categories = SelectMultipleField('Categories', choices=[])  # Choices will be populated in the view
    submit = SubmitField('Add Feed')
