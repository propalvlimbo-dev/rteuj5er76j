package ac.grim.grimac.utils.anticheat.update;

import com.github.retrooper.packetevents.protocol.world.BlockFace;
import com.github.retrooper.packetevents.protocol.world.states.type.StateType;
import com.github.retrooper.packetevents.util.Vector3f;
import com.github.retrooper.packetevents.util.Vector3i;

/**
 * EFC-совместимость: Grim BlockPlace.
 */
public class BlockPlace {

    public Vector3i position;
    public StateType material;
    public Vector3f cursor;

    private final BlockFace face;
    private Runnable efcResync;

    public BlockPlace(Vector3i position, StateType material, Vector3f cursor, BlockFace face) {
        this.position = position;
        this.material = material;
        this.cursor = cursor;
        this.face = face;
    }

    public BlockFace getFace() {
        return face;
    }

    public void onResync(Runnable efcResync) {
        this.efcResync = efcResync;
    }

    public void resync() {
        if (efcResync != null) {
            try {
                efcResync.run();
            } catch (Throwable ignored) {
            }
        }
    }
}
