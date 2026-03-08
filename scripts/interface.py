import bpy
import mido
from collections import deque

# ------------------------------------------------
# CONFIG
# ------------------------------------------------

MIDI_PORT_NAME = 'IAC Driver Bus 1'

MIDI_PPQ = 24
STEPS_PER_BEAT = 2
TICKS_PER_STEP = MIDI_PPQ // STEPS_PER_BEAT

# ------------------------------------------------
# RUNTIME STATE (THREAD SAFE)
# ------------------------------------------------

midi_queue = deque()
tick_counter = 0

midi_clock_port = None
midi_out = None

sequencers = {}
note_state = {}   # (channel, note) -> bool

# ------------------------------------------------
# MIDI CALLBACK (BACKGROUND THREAD)
# ------------------------------------------------

def midi_clock_callback(message):
    if message.type == 'clock':
        midi_queue.append('clock')
    elif message.type == 'cc':
        midi_queue.append('cc')
    elif message.type == 'start':
        midi_queue.append('start')
    elif message.type == 'stop':
        midi_queue.append('stop')

# ------------------------------------------------
# BLENDER MAIN THREAD
# ------------------------------------------------

def collect_sequencers():
    global sequencers
    sequencers = {
        ob.name: ob
        for ob in bpy.data.objects
        if ob.get('_MIDI') is not None
    }

def update_sequencers(depsgraph):
    for ob in sequencers.values():
        ob_eval = ob.evaluated_get(depsgraph)
        attrs = ob_eval.data.attributes

        if 'note_on' not in attrs or 'midi_note' not in attrs:
            continue

        note_on = bool(attrs['note_on'].data[0].value)
        note = int(attrs['midi_note'].data[0].value)
        channel = ob.midi_channel

        key = (channel, note)
        prev = note_state.get(key, False)

        # NOTE ON (rising edge)
        if note_on and not prev:
            midi_out.send(
                mido.Message(
                    'note_on',
                    channel=channel,
                    note=note,
                    velocity=100
                )
            )

        # NOTE OFF (falling edge)
        elif not note_on and prev:
            midi_out.send(
                mido.Message(
                    'note_off',
                    channel=channel,
                    note=note
                )
            )

        note_state[key] = note_on

def advance_one_tick():
    global tick_counter

    tick_counter += 1
    
    if tick_counter >= 2_147_483_647:
        tick_counter = 0

    timer = bpy.data.objects.get('TIMER')
    if timer:
        timer.location.x = tick_counter

    depsgraph = bpy.context.evaluated_depsgraph_get()
    update_sequencers(depsgraph)


def reset_transport():
    global tick_counter
    tick_counter = 0

    timer = bpy.data.objects.get('TIMER')
    if timer:
        timer.location.x = 0

def process_midi_queue():
    clocks = 0

    while midi_queue:
        msg = midi_queue.popleft()

        if msg == 'clock':
            clocks += 1
        elif msg == 'start':
            reset_transport()
        elif msg == 'stop':
            pass

    # ADVANCE ONCE PER RECEIVED CLOCK
    for _ in range(clocks):
        advance_one_tick()

    return 0.0

# ------------------------------------------------
# OPERATORS
# ------------------------------------------------

class StartMidiSync(bpy.types.Operator):
    """Start MIDI Sync"""
    bl_idname = "scene.start_midi_sync"
    bl_label = "Start MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out

        collect_sequencers()

        midi_clock_port = mido.open_input(MIDI_PORT_NAME)
        midi_clock_port.callback = midi_clock_callback

        midi_out = mido.open_output(MIDI_PORT_NAME)

        bpy.app.timers.register(process_midi_queue)

        print("MIDI sync started")

        return {'FINISHED'}

class StopMidiSync(bpy.types.Operator):
    """Stop MIDI Sync"""
    bl_idname = "scene.stop_midi_sync"
    bl_label = "Stop MIDI Sync"

    def execute(self, context):
        global midi_clock_port, midi_out

        if midi_clock_port:
            midi_clock_port.close()
            midi_clock_port = None

        if midi_out:
            midi_out.close()
            midi_out = None

        print("MIDI sync stopped")

        return {'FINISHED'}

# ------------------------------------------------
# REGISTER
# ------------------------------------------------

def register():
    bpy.utils.register_class(StartMidiSync)
    bpy.utils.register_class(StopMidiSync)

    bpy.types.Object.midi_channel = bpy.props.IntProperty(
        name="MIDI Channel",
        default=0,
        min=0,
        max=15
    )

def unregister():
    bpy.utils.unregister_class(StartMidiSync)
    bpy.utils.unregister_class(StopMidiSync)

if __name__ == "__main__":
    register()
