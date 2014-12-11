
# Helper script to boot the identified exe in QEMU.

import os
import argparse
import subprocess
import shutil

def parseargs():
    """
    Parse and validate arguments to the program. We do basic, but not
    exhaustive, sanity checking. 
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("rtdir", help="Path of RTEMS builder directory (~/dev/rtems)")
    parser.add_argument("exefile", help="Full path to built executable (.../hello/hello.exe)")
    parser.add_argument("-o", "--outfile", help="Destination to copy disk image file after creation")
    parser.add_argument("-x", "--execute", action="store_true", help="Start qemu after building image")
    parser.add_argument("-b", "--bsize", type=int, default=512, help="Size of disk img block size in bytes")
    parser.add_argument("-s", "--imgsize", type=int, default=30, help="Size of the disk image in MiB")
    parser.add_argument("-t", "--tmpdir", help="Temporary directory to store working files")
    args = parser.parse_args()

    # Sanity check of required arguments
    if not os.path.isdir(args.rtdir):
        parser.error("RTEMS directory not found: {}".format(args.rtdir))
    qemudir = os.path.join(args.rtdir, "qemu-linaro")
    if not os.path.isdir(qemudir):
        print "This script needs the Linaro Qemu built, expected in {}".format(qemudir)
        print "Is the bbxm.bset from the RTEMS source builder built?"
        parser.error("qemu-linaro directory not found in {}".format(args.rtdir))
    if not os.path.exists(args.exefile):
        print "You must specify an executable to package in an image."
        parser.error("executable {} not found".format(args.exefile))
    if "outfile" not in args and not args.execute:
        print "No outfile specified, and no qemu execution requested. This would"
        print "generate an image, do nothing with it, and then delete it. Skipping."
        parser.error("must specify at least one of -o or -x")
    if 'tmpdir' in args and not os.path.isdir(args.tmpdir):
        parser.error("Specified temporary directory does not exist: {}".format(args.tmpdir))
    if 'outfile' in args and os.path.exists(args.outfile):
        parser.error("Destination image file already exists: {}".format(args.outfile))

    return args

def build_image(rtdir, exefile, bsize, imgsize, tmpdir):
    """
    Perform the steps necessary to create a blank image, and then populate
    it. Because we create a bare image, and also a FAT image, the disk space
    required is approximately 2*imgsize.
    """
    img_fn   = os.path.join(tmpdir, "bbxm_boot_sdcard.img")
    fat_fn   = os.path.join(tmpdir, "bbxm_boot_fat.img")
    app_name = "rtems_app.img"
    app_fn   = os.path.join(tmpdir, app_name)
    uenv_fn  = os.path.join(tmpdir, "uEnv.txt")
    sd_size  = imgsize * (1024*1024) / bsize # we don't bother writing all the zeroes, just allocate the file
    offset   = (1024*1024) / bsize # FAT offset within the disk image
    fat_size = sd_seek - offset

    zero_img(img_fn, bsize, sd_size)
    zero_img(fat_fn, bsize, fat_size-1)
    partition_image(rtdir, img_fn, offset)
    format_fat(fat_fn, bsize, fat_size)

    prep_exe(rtdir, exefile, tmpdir, app_fn)
    write_uenv(uenv_fn, app_name)

    copy_file_to_fat(rtdir, fat_fn, os.path.join(rtdir, "uboot", "omap3_beagle", "MLO"))
    copy_file_to_fat(rtdir, fat_fn, os.path.join(rtdir, "uboot", "omap3_beagle", "u_boot.img"))
    copy_file_to_fat(rtdir, fat_fn, app_fn)
    copy_file_to_fat(rtdir, fat_fn, uenv_fn)

    copy_fat_to_img(img_fn, fat_fn, offset)
    
    return img_fn

def zero_img(img_fn, bsize, seek):
    """
    Use dd to create a blank (all zeroes) file. To avoid actually writing zeroes,
    we use seek to skip to the last block.
    """
    try:
        subprocess.check_output([ 'dd', 
            'if=/dev/zero', 
            'of={}'.format(img_fn), 
            'bs={}'.format(bsize), 
            'seek={}'.format(seek),
            'count=1' ])
    except subprocess.CalledProcessError as e:
        os.remove(img_fn)
        raise RuntimeError("writing file {} failed with error {}: {}".format(img_fn, e.retcode, e.output))

def format_fat(fat_fn, bsize, fs_size):
    """
    Use BSD's newfs_msdos to write a FAT filesystem onto the specified file.
    """
    try:
        subprocess.check_output([ os.path.join(rtdir, "bin", "newfs_msdos"),
            '-r', '1', '-m', '0xf8', '-c', '4', '-F16', '-h', '64', '-u', '32', '-o', '0',
            '-S', bsize,
            '-s', fs_size, 
            fat_fn ])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("formatting image {} failed with error {}: {}".format(fat_fn, e.retcode, e.output))

def prep_exe(rtdir, exefile, tmpdir, app_fn):
    """
    Use GNU objcopy to turn an ELF relocatable binary (".exe") into a bare
    binary, and gzip it. Then, use U-Boot's mkimage helper to turn that bare
    binary into a "U-Boot image", destined for memory address 0x80000000.

    We leave this transformed binary in the working directory, and do not copy it out.
    """
    exebase = os.path.basename(exefile)
    binfile = os.path.join(tmpdir, exebase + ".bin")
    try:
        subprocess.check_output([ os.path.join(rtdir, "bin", "arm-rtems4.11-objcopy"),
            exefile, '-O', 'binary', binfile ])
        subprocess.check_output([ 'gzip', '-9', binfile ])
        subprocess.check_output([ os.path.join(rtdir, "bin", "mkimage"),
            '-A', 'arm', '-T', 'kernel', '-a', '0x80000000', '-e', '0x80000000', '-O', 'rtems', '-n', 'RTEMS', 
            '-d', binfile + '.gz', 
            os.path.join(tmpdir, app_fn) ])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("failed to prep exe: {}".format(repr(e)))

def copy_file_to_fat(rtdir, fatimg, copy_fn):
    """ Copy the specified file into the root of the specified FAT disk image file. """
    copy_base = os.path.basename(copy_fn)
    try:
        subprocess.check_output([ os.path.join(rtdir, "bin", "mcopy"),
            '-bsp', '-i', fatimg, copy_fn, '::' + copy_base ])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("failed to copy file {} to image {}: {}".format(copy_fn, fatimg, repr(e)))

def partition_img(rtdir, sd_img, offset):
    """ Create a partition table with a single entry in the specified image file """
    try:
        subprocess.check_output([ os.path.join(rtdir, "bin", "partition"),
            '-m', sd_img, offset, 'c:0*+' ])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("failed to partition image: {}".format(repr(e)))

def copy_fat_to_img(sd_img, fat_img, offset):
    """ 
    Directly write the specified FAT disk image file onto the larger SD card
    image file, offset by a sufficient amount.
    """
    try:
        subprocess.check_output([ 'dd',
            'of={}'.format(sd_img), 'if={}'.format(fat_img), 'seek={}'.format(offset) ])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("failed to copy fat image: {}".format(repr(e)))

def main():
    # Gather information from the command line, doing basic sanity checking.
    args = parseargs()

    # If we weren't handed a temp dir, create one.
    if 'tmpdir' not in args:
        import tempfile
        args.tmpdir = tempfile.mkdtemp()

    # Create the disk image within the temp directory.
    outimg = build_image(args.rtdir, args.exefile, args.bsize, args.imgsize, args.tmpdir)

    # Copy the image file out of the temp directory if requested.
    if "outfile" in args:
        shutil.copyfile(outimg, args.outfile)

    # Invoke qemu-linaro's qemu-system-arm program to boot the newly created SD card image
    # TODO: Make this appropriate/flexible for the various BB* targets.
    if args.execute:
        subprocess.call([ os.path.join(args.rtdir, "qemu-linaro", "bin", "qemu-system-arm"),
            '-display', 'none', '-serial', 'stdio', '-M', 'beaglexm', '-no-reboot',
            '-monitor', 'none', '-nographic', '-sd', outimg])

    # Delete the working directory.
    shutil.rmtree(args.tmpdir)

if __name__=="__main__":
    main()
