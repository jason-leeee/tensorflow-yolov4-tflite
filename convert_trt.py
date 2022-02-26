from absl import app, flags, logging
from absl.flags import FLAGS
import tensorflow as tf
#physical_devices = tf.config.experimental.list_physical_devices('GPU')
#if len(physical_devices) > 0:
#    tf.config.experimental.set_memory_growth(physical_devices[0], True)
#tf.config.gpu.set_per_process_memory_fraction(0.4)

from tensorflow.compat.v1 import ConfigProto
from tensorflow.compat.v1 import InteractiveSession

config = ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = 0.4
config.gpu_options.allow_growth = True
session = InteractiveSession(config=config)

import numpy as np
import cv2
from tensorflow.python.compiler.tensorrt import trt_convert as trt
import core.utils as utils
from tensorflow.python.saved_model import signature_constants
import os
from tensorflow.compat.v1 import ConfigProto
from tensorflow.compat.v1 import InteractiveSession

flags.DEFINE_string('weights', './checkpoints/yolov4-416', 'path to weights file')
flags.DEFINE_string('output', './checkpoints/yolov4-trt-fp16-416', 'path to output')
flags.DEFINE_integer('input_size', 416, 'path to output')
flags.DEFINE_string('quantize_mode', 'float16', 'quantize mode (int8, float16)')
flags.DEFINE_string('dataset', '', 'path to dataset')   # "./scripts/coco/5k.txt"
flags.DEFINE_bool('build_engine', False, 'build engine while converting, with or without dataset')
flags.DEFINE_integer('batch_size', 8, 'maximum batch size')

def representative_data_gen():
  batched_input = np.zeros((FLAGS.batch_size, FLAGS.input_size, FLAGS.input_size, 3), dtype=np.float32)

  if FLAGS.dataset:
    # fill batched_input with real data, otherwise just mock up with a 0-valued array
    fimage = open(FLAGS.dataset).read().split()
    for input_value in range(FLAGS.batch_size):
      if os.path.exists(fimage[input_value]):
        original_image=cv2.imread(fimage[input_value])
        original_image = cv2.cvtColor(original_image, cv2.COLOR_BGR2RGB)
        image_data = utils.image_preporcess(np.copy(original_image), [FLAGS.input_size, FLAGS.input_size])
        img_in = image_data[np.newaxis, ...].astype(np.float32)
        batched_input[input_value, :] = img_in
        # batched_input = tf.constant(img_in)
        print(input_value)
        # yield (batched_input, )
        # yield tf.random.normal((1, 416, 416, 3)),
      else:
        continue
  
  batched_input = tf.constant(batched_input)
  yield (batched_input,)

def save_trt():
  print("Start converting")
  if FLAGS.quantize_mode == 'int8':
    conversion_params = trt.DEFAULT_TRT_CONVERSION_PARAMS._replace(
      precision_mode=trt.TrtPrecisionMode.INT8,
      max_workspace_size_bytes=(1 << 32),   # 4GB
      use_calibration=True,
      max_batch_size=FLAGS.batch_size)
    converter = trt.TrtGraphConverterV2(
      input_saved_model_dir=FLAGS.weights,
      conversion_params=conversion_params)
    converter.convert(calibration_input_fn=representative_data_gen)
  elif FLAGS.quantize_mode == 'float16':
    conversion_params = trt.DEFAULT_TRT_CONVERSION_PARAMS._replace(
      precision_mode=trt.TrtPrecisionMode.FP16,
      max_workspace_size_bytes=(1 << 32),   # 4GB
      max_batch_size=FLAGS.batch_size)
    converter = trt.TrtGraphConverterV2(
      input_saved_model_dir=FLAGS.weights, conversion_params=conversion_params)
    converter.convert()
  else :
    conversion_params = trt.DEFAULT_TRT_CONVERSION_PARAMS._replace(
      precision_mode=trt.TrtPrecisionMode.FP32,
      max_workspace_size_bytes=(1 << 32),   # 4GB
      max_batch_size=FLAGS.batch_size)
    converter = trt.TrtGraphConverterV2(
      input_saved_model_dir=FLAGS.weights, conversion_params=conversion_params)
    converter.convert()

  print("Start building engine")
  if FLAGS.build_engine:
    converter.build(input_fn=representative_data_gen)
  
  converter.save(output_saved_model_dir=FLAGS.output)
  print('Done Converting to TF-TRT')

  print("Validating the conversion")
  saved_model_loaded = tf.saved_model.load(FLAGS.output)
  graph_func = saved_model_loaded.signatures[
    signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY]
  trt_graph = graph_func.graph.as_graph_def()
  for n in trt_graph.node:
    print(n.op)
    if n.op == "TRTEngineOp":
      print("Node: %s, %s" % (n.op, n.name.replace("/", "_")))
    else:
      print("Exclude Node: %s, %s" % (n.op, n.name.replace("/", "_")))
  logging.info("model saved to: {}".format(FLAGS.output))

  trt_engine_nodes = len([1 for n in trt_graph.node if str(n.op) == 'TRTEngineOp'])
  print("numb. of trt_engine_nodes in TensorRT graph:", trt_engine_nodes)
  all_nodes = len([1 for n in trt_graph.node])
  print("numb. of all_nodes in TensorRT graph:", all_nodes)

def main(_argv):
  config = ConfigProto()
  config.gpu_options.allow_growth = True
  session = InteractiveSession(config=config)
  save_trt()

if __name__ == '__main__':
    try:
        app.run(main)
    except SystemExit:
        pass
