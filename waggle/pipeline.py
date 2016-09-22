from datetime import datetime
import json
from multiprocessing import Process, Queue
import pika
import time


class Plugin(object):

    def __init__(self, name, man, outqueue):
        if not hasattr(self, 'plugin_name'):
            raise RuntimeError('Plugin name must be specified.')

        if not hasattr(self, 'plugin_version'):
            raise RuntimeError('Plugin version must be specified.')

        self.name = name
        self.man = man
        self.outqueue = outqueue

        # think about using empty credentials for this and filtering
        # bad items.
        credentials = pika.PlainCredentials('node', 'node')

        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters('localhost',
                                      credentials=credentials))

        self.channel = self.connection.channel()

        self.channel.queue_declare(queue='data-check',
                                   durable=True)

    def send(self, sensor, data):
        assert isinstance(sensor, str)

        now = time.time()
        timestamp_epoch = int(now * 1000)
        timestamp_utc = int(now)
        timestamp_date = time.strftime('%Y-%m-%d', time.gmtime(timestamp_utc))

        message_data = [
            str(timestamp_date),
            self.plugin_name,
            self.plugin_version,
            '',
            timestamp_epoch,
            sensor,
            '',
            data,
        ]

        self.outqueue.put(message_data)

        if isinstance(data, int):
            # consider packing certain types to save space.
            # can also consider automatically applying zlib
            # if it makes sense on the data. it'd be even
            # better if we could take advantage of protobufs
            # or some standard, open encoding technique.
            # data = struct.pack('>i', data)
            data = str(data).encode()
            datatype = 'i'
        elif isinstance(data, float):
            # data = struct.pack('>f', data)
            data = str(data).encode()
            datatype = 'f'
        elif isinstance(data, str):
            data = data.encode()
            datatype = 's'
        elif isinstance(data, bytearray):
            data = bytes(data)
            datatype = 'b'
        elif isinstance(data, bytes):
            datatype = 'b'
        else:
            raise ValueError('unsupported data type')

        # forward to rmq
        properties = pika.BasicProperties(
            type=datatype,
            headers={
                'plugin': [self.plugin_name, self.plugin_version, ''],
                'sensor': sensor,
            }
        )

        self.channel.basic_publish(properties=properties,
                                   exchange='',
                                   routing_key='data-check',
                                   body=data)

    def run(self):
        raise NotImplemented('Plugin must define run method.')


class Worker(object):

    def __init__(self, host='localhost'):
        if not hasattr(self, 'plugin_name'):
            raise RuntimeError('Plugin name must be specified.')

        if not hasattr(self, 'plugin_version'):
            raise RuntimeError('Plugin version must be specified.')

        self.queue_name = '.'.join([self.plugin_name, self.plugin_version])
        self.routing_key = '.'.join([self.plugin_name, self.plugin_version])

        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host))

        self.channel = self.connection.channel()

        self.channel.queue_declare(queue=self.queue_name)

        self.channel.queue_bind(exchange='x-plugins-in',
                                queue=self.queue_name,
                                routing_key=self.routing_key)

    def get_message(self, headers, param, value):
        pass

    def put_message(self, headers, payload):
        payload.update({
            'node_id': '00A',
            'node_config': '123abc',
            'datetime': datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f'),
        })

        self.channel.basic_publish(exchange='x-plugins-out',
                                   routing_key='',
                                   # routing_key='envsense.2',
                                   body=json.dumps(payload))

    def start(self):
        def callback(ch, method, properties, body):
            headers = properties.headers
            param = tuple(headers['sensor'])
            self.get_message(headers, param, body)

        self.channel.basic_consume(callback, queue=self.queue_name, no_ack=True)
        self.channel.start_consuming()


def run_standalone(plugin, callback):

    def register(name, man, mailbox_outgoing):
        plugin(name, man, mailbox_outgoing).run()

    q = Queue()
    p = Process(target=register, args=(plugin.plugin_name, {}, q))
    p.start()

    while True:
        callback(q.get())
