package com.github.retrooper.packetevents.protocol.entity.type;

/** Compile-only стаб. В jar не попадает. */
public class EntityType {

    private final String name;

    public EntityType(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }
}
