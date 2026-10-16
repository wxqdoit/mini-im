import os
import uuid
from contextlib import contextmanager

_tracer = None
_is_initialized = False

def init_telemetry(service_name: str = None):
    global _tracer, _is_initialized
    if _is_initialized:
        return _tracer

    role = os.getenv("SERVICE_ROLE", "all")
    actual_service_name = service_name or f"mini-im-{role}"
    
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        resource = Resource.create({"service.name": actual_service_name, "service.version": "1.0.0"})
        provider = TracerProvider(resource=resource)

        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
        
        # Configure OTLP HTTP Exporter with a short timeout so offline Jaeger won't block execution
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, timeout=2)
            span_processor = BatchSpanProcessor(otlp_exporter, max_queue_size=2048, schedule_delay_millis=500)
            provider.add_span_processor(span_processor)
        except Exception as e:
            print(f"[Telemetry] Warning adding OTLP exporter: {e}")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("mini-im-tracer")
        _is_initialized = True
        print(f"[Telemetry] OpenTelemetry initialized successfully for '{actual_service_name}' (Endpoint: {otlp_endpoint})")
    except Exception as e:
        print(f"[Telemetry] OpenTelemetry initialization failed (fallback to mock): {e}")
        _tracer = None
        _is_initialized = True

    return _tracer

def get_tracer():
    global _tracer
    if not _is_initialized:
        init_telemetry()
    return _tracer

def inject_trace_context(carrier: dict = None) -> dict:
    if carrier is None:
        carrier = {}
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        TraceContextTextMapPropagator().inject(carrier)
    except Exception:
        if "traceparent" not in carrier:
            tid = uuid.uuid4().hex
            carrier["traceparent"] = f"00-{tid}-0000000000000001-01"
            carrier["trace_id"] = tid
    return carrier

def extract_trace_context(carrier: dict):
    if not carrier:
        return None
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        return TraceContextTextMapPropagator().extract(carrier)
    except Exception:
        return None

def get_current_trace_id() -> str:
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except Exception:
        pass
    return uuid.uuid4().hex

@contextmanager
def trace_span(span_name: str, attributes: dict = None, parent_carrier: dict = None):
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    try:
        from opentelemetry import trace
        ctx = extract_trace_context(parent_carrier) if parent_carrier else None
        with tracer.start_as_current_span(span_name, context=ctx) as span:
            if attributes:
                for k, v in attributes.items():
                    if v is not None:
                        span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool, str)) else v)
            yield span
    except Exception as e:
        yield None
