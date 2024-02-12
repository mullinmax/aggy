from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, URL

class FeedForm(FlaskForm):
    name = StringField('Feed Name', validators=[DataRequired()])
    url = StringField('RSS URL', validators=[DataRequired(), URL()])
    category = StringField('Category', validators=[DataRequired()])
    submit = SubmitField('Add Feed')
