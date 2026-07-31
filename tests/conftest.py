import os
import boto3
import pytest
from app.db import db
from app import create_app
from dotenv import load_dotenv
from moto import mock_aws
from app.models.order import Order
from app.models.line_item import LineItem
from flask.signals import request_finished

load_dotenv()

@pytest.fixture
def aws_credentials():
    os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"

@pytest.fixture
def app(mock_aws_context):
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": os.environ.get('SQLALCHEMY_TEST_DATABASE_URI')
    }

    app = create_app(test_config)

    @request_finished.connect_via(app)
    def expire_session(sender, response, **extra):
        db.session.remove()

    with app.app_context():
        db.create_all()
        yield app

    with app.app_context():
        db.drop_all()

@pytest.fixture
def mock_aws_context(aws_credentials):
    with mock_aws():
        yield

@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sns_mock(app):
    """
    Creates a moto-mocked SNS FIFO topic and an SQS FIFO queue subscribed to
    it so that every SNS publish during a test is captured and inspectable.
    Relies on mock_aws_context (via app) already being active.
    """
    sns_client = boto3.client("sns", region_name=os.environ["AWS_DEFAULT_REGION"])
    sqs_client = boto3.client("sqs", region_name=os.environ["AWS_DEFAULT_REGION"])

    topic_resp = sns_client.create_topic(
        Name="order-placed.fifo",
        Attributes={
            "FifoTopic": "true",
            "ContentBasedDeduplication": "false",
        },
    )
    topic_arn = topic_resp["TopicArn"]

    queue_resp = sqs_client.create_queue(
        QueueName="test-orders.fifo",
        Attributes={
            "FifoQueue": "true",
            "ContentBasedDeduplication": "true",
        },
    )
    queue_url = queue_resp["QueueUrl"]
    queue_arn = sqs_client.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    sns_client.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)

    os.environ["ARN"] = topic_arn

    yield {
        "sns_client": sns_client,
        "sqs_client": sqs_client,
        "topic_arn": topic_arn,
        "queue_url": queue_url,
    }

    os.environ.pop("ARN", None)


@pytest.fixture
def one_order_with_items(app):

    order = Order(user_id=10)
    db.session.add(order)
    db.session.flush()

    items = [
        LineItem(order_id=order.id, product_id="A1",
                  product_name="Widget", product_price=9.99, quantity=2),
        LineItem(order_id=order.id, product_id="B2",
                  product_name="Gadget", product_price=24.99, quantity=1),
    ]
    db.session.add_all(items)
    db.session.commit()
    return order.to_dict()


@pytest.fixture
def two_orders_with_items(app):

    order1 = Order(user_id=1)
    order2 = Order(user_id=2)
    db.session.add_all([order1, order2])
    db.session.flush()

    items = [
        LineItem(order_id=order1.id, product_id="A1",
                  product_name="Widget", product_price=9.99, quantity=2),
        LineItem(order_id=order1.id, product_id="B2",
                  product_name="Gadget", product_price=24.99, quantity=1),
        LineItem(order_id=order2.id, product_id="C3",
                  product_name="Doohickey", product_price=4.99, quantity=3),
        LineItem(order_id=order2.id, product_id="D4",
                  product_name="Thingamajig", product_price=14.49, quantity=1),
    ]
    db.session.add_all(items)
    db.session.commit()
    return [order1.to_dict(), order2.to_dict()]