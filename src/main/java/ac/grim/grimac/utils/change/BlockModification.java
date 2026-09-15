package ac.grim.grimac.utils.change;

import com.github.retrooper.packetevents.protocol.world.states.type.StateType;
import com.github.retrooper.packetevents.util.Vector3i;

/**
 * EFC-совместимость: Grim BlockModification.
 */
public class BlockModification {

    private final Cause cause;
    private final Vector3i location;
    private final int tick;
    private final StateType oldType;

    public BlockModification(Cause cause, Vector3i location, int tick, StateType oldType) {
        this.cause = cause;
        this.location = location;
        this.tick = tick;
        this.oldType = oldType;
    }

    public Cause cause() {
        return cause;
    }

    public Vector3i location() {
        return location;
    }

    public int tick() {
        return tick;
    }

    public OldContents oldBlockContents() {
        return new OldContents(oldType);
    }

    public enum Cause {
        START_DIGGING,
        HANDLE_NETTY_SYNC_TRANSACTION
    }

    public static final class OldContents {
        private final StateType type;

        public OldContents(StateType type) {
            this.type = type;
        }

        public StateType getType() {
            return type;
        }
    }
}
