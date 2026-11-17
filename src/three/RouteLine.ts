import * as THREE from 'three';

/** 导航路线的三维管线与终点标记 */
export class RouteLine {
  private line: THREE.Line;
  private marker: THREE.Mesh;
  readonly group = new THREE.Group();

  constructor() {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3));
    const mat = new THREE.LineBasicMaterial({ color: 0x0a84ff, linewidth: 2 });
    this.line = new THREE.Line(geo, mat);
    this.line.frustumCulled = false;

    this.marker = new THREE.Mesh(
      new THREE.CylinderGeometry(0.7, 0.7, 0.25, 20),
      new THREE.MeshBasicMaterial({ color: 0x0a84ff }),
    );
    this.marker.position.y = 0.15;
    this.marker.visible = false;

    this.group.add(this.line, this.marker);
    this.group.visible = false;
  }

  setRoute(points: { x: number; z: number }[]): void {
    if (points.length < 2) {
      this.group.visible = false;
      return;
    }
    const pos = new Float32Array(points.length * 3);
    points.forEach((p, i) => {
      pos[i * 3] = p.x;
      pos[i * 3 + 1] = 0.12;
      pos[i * 3 + 2] = p.z;
    });
    this.line.geometry.dispose();
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.line.geometry = geo;

    const end = points[points.length - 1];
    this.marker.position.set(end.x, 0.15, end.z);
    this.marker.visible = true;
    this.group.visible = true;
  }

  clear(): void {
    this.group.visible = false;
    this.marker.visible = false;
  }
}
